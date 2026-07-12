# Plan: vRising Discord Bot

## Context

Building a Discord bot that runs in a Docker container on a Synology NAS to let the owner
and friends start/stop a pre-existing vRising game server container via slash commands.
The bot controls the vRising container through a docker-socket-proxy (security isolation),
auto-shuts down the server after a configurable number of hours, and cancels the timer if
a user manually stops the server first. Reusing an existing bot application (LinkBot#0033)
— old `/satisfactory` guild commands will be wiped during first sync.

---

## Project Structure

```
linkbot-discord/
├── docker-compose.yml          # bot stack: proxy + bot
├── .env.example                # template for all env vars
├── .gitignore                  # excludes .env, __pycache__, .venv, etc.
├── bot/
│   ├── Dockerfile
│   ├── pyproject.toml          # uv-managed deps + project metadata
│   ├── uv.lock                 # committed lockfile (reproducible builds)
│   ├── main.py                 # bot setup, cog loading, on_ready
│   ├── config.py               # env var loading + validation (fails fast if missing)
│   ├── docker_client.py        # thin wrapper around docker-py via proxy URL
│   ├── cogs/
│   │   └── vrising.py          # /vrising command group + auto-shutdown logic
│   └── sync_commands.py        # one-shot script: clear old commands, register new ones
```

---

## Key Decisions (settled)

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python 3.14 | User preference; fall back to 3.13-slim if 3.14 image not yet published |
| Dependency management | `uv` + `pyproject.toml` + `uv.lock` | Modern, fast; lockfile ensures reproducible container builds |
| Discord library | discord.py 2.x | Stable, native app_commands for slash commands |
| Docker library | docker-py (`docker`) | Connects to proxy URL instead of socket |
| Permission model | Discord integration permissions (role-based in UI) + guild ID check in code | No role API calls needed; roles payload is in the interaction |
| Command scope | Guild commands (scoped to one server ID) | Slash commands unavailable in DMs; instant sync; no global pollution |
| Container targeting | `TARGET_CONTAINER_NAME` env var | Simpler than label-based for a single-container use case |
| Auto-shutdown timer | `asyncio.Task` (sleep + stop) | Native to discord.py's async loop; cancellable with `.cancel()` |
| Command sync | Manual `sync_commands.py` run via `docker compose run --rm`, not on-startup | discord.py best practice; avoids rate limits on restarts |
| Deployment | Build on NAS via SSH + git pull, no registry | Simplest; avoids Docker Hub account and push/pull workflow |

---

## Environment Variables

**In `.env`** (gitignored; all deployment-specific or secret values):
```
DISCORD_BOT_TOKEN=          # bot token from Discord developer portal
DISCORD_GUILD_ID=           # your server's ID (right-click server → Copy ID)
TARGET_CONTAINER_NAME=      # exact name of the vRising Docker container
NOTIFICATION_CHANNEL_ID=    # channel ID where auto-shutdown notices are posted
DEFAULT_SHUTDOWN_HOURS=6    # default if user doesn't supply hours to /vrising start
MAX_SHUTDOWN_HOURS=24       # upper bound for user-supplied duration
```

**In `docker-compose.yml` `environment:` block** (static internal infrastructure, same on every deploy):
```
DOCKER_PROXY_URL=http://docker-proxy:2375
```

---

## `docker-compose.yml` (bot stack)

The proxy was initially implemented using `tecnativa/docker-socket-proxy` (a haproxy wrapper
with env-var-driven ACLs). It was replaced with `haproxy:lts-alpine` + a custom config after
a security review identified that `POST=1` combined with `CONTAINERS=1` — both required for
the bot to function — also permitted `POST /containers/create`. A compromised bot could use
this to create a new container with host volume mounts, exposing the NAS filesystem.
tecnativa provides no env var to block just that endpoint.

The custom config is ~15 lines and covers exactly the four paths docker-py uses. Everything
else, including `/containers/create`, is denied by default. See `docker-proxy/haproxy.cfg`.

```yaml
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      CONTAINERS: 1
      START: 1
      STOP: 1
      # all others default to 0 (blocked)
    networks: [bot-internal]
    restart: unless-stopped

  bot:
    build: ./bot
    env_file: .env
    environment:
      DOCKER_PROXY_URL: http://docker-proxy:2375
    networks: [bot-internal]
    depends_on: [docker-proxy]
    restart: unless-stopped
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }

networks:
  bot-internal:
    driver: bridge
```

No ports exposed on either service. The proxy port is unreachable outside the internal network.

---

## `bot/Dockerfile`

```dockerfile
FROM python:3.14-slim
# If 3.14 image not yet published, use python:3.13-slim and bump when 3.14 ships (Oct 2025)

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Dependency layer (cached unless pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "main.py"]
```

---

## Bot Application Design

### `config.py`
Loads all env vars at import time; raises `RuntimeError` with a clear message if any required
var is missing. All other modules import from here — no scattered `os.getenv` calls.

### `docker_client.py`
```python
import docker
client = docker.DockerClient(base_url=config.DOCKER_PROXY_URL)

def get_container()       # returns Container or raises NotFound
def start_container()     # container.start()
def stop_container()      # container.stop()
def container_status()    # returns container.status string ("running", "exited", ...)
```
All docker-py calls are blocking (sync library); wrap them in `asyncio.to_thread()` inside
the cog so they don't block the event loop.

### `cogs/vrising.py` — command group `/vrising`

**State held on the cog instance:**
```python
self.shutdown_task: asyncio.Task | None = None   # cancel handle
self.shutdown_at:   datetime | None = None        # for /status time-remaining display
```

**`/vrising start [hours]`**
- `hours`: optional int, default `DEFAULT_SHUTDOWN_HOURS`, min 1, max `MAX_SHUTDOWN_HOURS`
- Discord UI shows it as a plain integer parameter (type `/vrising start 4`, not `4h`)

Logic:
1. Guild ID check — silently ignore if not from our server
2. Defer response
3. If container not running: start it via `docker_client.start_container()`
4. If container already running: inform user we're rescheduling (no start call needed)
5. Cancel existing `shutdown_task` if set
6. Create new `asyncio.Task(_auto_shutdown(hours))`; store handle + `shutdown_at`
7. Reply: "Server started/already running. Auto-shutdown in X h at HH:MM UTC."

**`/vrising stop`**
1. Guild ID check
2. Cancel `shutdown_task` if set; clear `shutdown_at`
3. Stop container via `docker_client.stop_container()`
4. Reply with confirmation

**`/vrising status`**
1. Guild ID check
2. Get container status
3. If running + `shutdown_at` set: include "Auto-shutdown in X h Y m (at HH:MM UTC)"
4. If running + no timer: note "No auto-shutdown scheduled"
5. Reply with formatted status

**`_auto_shutdown(hours)` coroutine**
```python
async def _auto_shutdown(self, hours: int):
    try:
        await asyncio.sleep(hours * 3600)
    except asyncio.CancelledError:
        return                               # user stopped manually — clean exit
    await asyncio.to_thread(docker_client.stop_container)
    self.shutdown_task = None
    self.shutdown_at = None
    channel = bot.get_channel(config.NOTIFICATION_CHANNEL_ID)
    if channel:
        await channel.send("vRising server auto-shutdown complete.")
```

**`on_ready` handler (in `main.py`)**
- If vRising container is found running at startup: schedule `_auto_shutdown(DEFAULT_SHUTDOWN_HOURS)` immediately and post a notice to `NOTIFICATION_CHANNEL_ID`: "Bot restarted. vRising server found running — auto-shutdown scheduled in X h."
- This covers the case where the bot crashed/restarted mid-session.

### `sync_commands.py` (run once after deploy, or after command changes)
```bash
docker compose run --rm bot python sync_commands.py
```
1. Logs in with bot token
2. Clears all **global** commands (`tree.clear_commands(guild=None); await tree.sync()`)
   → removes old `/satisfactory` global commands if any exist
3. Registers and syncs **guild** commands to `DISCORD_GUILD_ID`
   → replaces all existing guild commands for this server (old `/satisfactory` included)
4. Prints confirmation and exits

---

## Multi-Server Support (future)

Support multiple game server containers, each mapped to its own slash command group
(e.g. `/vrising`, `/satisfactory`), driven by a config file rather than hardcoded class
definitions.

### Config

A committed `servers.yml` (no secrets — container names are not sensitive):

```yaml
servers:
  - command: vrising
    container: vrising11
  - command: satisfactory
    container: satisfactory1
```

`TARGET_CONTAINER_NAME` in `.env` goes away; all server mappings live in `servers.yml`.

### discord.py approach

The current `VRising(commands.GroupCog, name="vrising")` pattern bakes the slash command
group name into the class definition at write time — you can't set `name=` from a variable.

For dynamic names from config, use `app_commands.Group` directly (the lower-level primitive
that `GroupCog` wraps). Groups are instantiated at runtime with whatever name the config
provides, then registered on the bot's command tree:

```python
group = app_commands.Group(name="satisfactory", description="...")
bot.tree.add_command(group)
```

`app_commands.Group` is a fully supported first-class discord.py pattern — `GroupCog` is
just an ergonomic shortcut for the static case.

### Refactor scope

- Generalize `VRising` cog → `ServerCog`, taking `command_name` + `container_name` as
  constructor params. Strip vRising-specific flavor text (or make it configurable per entry).
- `main.py` reads `servers.yml` and registers one `ServerCog` per entry.
- `sync_commands.py` loads the same cogs — picks up all groups automatically, no changes
  needed.
- If haproxy name-filtering is desired (see haproxy notes), the allowed container name list
  can be generated from `servers.yml` at proxy startup.

---

## RCON (v2 — not in this build)

vRising supports RCON (port 25575). Future extension: add warning messages inside
`_auto_shutdown` at T-30m and T-10m using the `mcrcon` Python package. Requires
`RCON_HOST`, `RCON_PORT`, `RCON_PASSWORD` env vars. No structural changes to the
bot architecture — slots into the existing coroutine.

---

## Deployment (Synology NAS)

```bash
# One-time setup
ssh you@nas
git clone <your-repo> ~/docker/linkbot-discord
cd ~/docker/linkbot-discord
cp .env.example .env
nano .env                                         # fill in token, guild ID, etc.
docker compose up -d --build                      # builds image on NAS, starts stack

# Register slash commands (once, or after command changes)
docker compose run --rm bot python sync_commands.py

# Future updates
git pull && docker compose up -d --build
```

No Docker Hub account or image registry needed. Docker builds the image locally on the NAS.

---

## Build Order

1. Scaffold repo: `.gitignore`, `.env.example`, `docker-compose.yml`, `bot/pyproject.toml`
2. Spin up `docker-proxy` alone; verify:
   - Allowed: `curl http://docker-proxy:2375/containers/json` (from bot network) → 200
   - Blocked: `curl -X POST http://docker-proxy:2375/images/create` → 403
   - Not reachable from host (port not published)
3. Write `config.py`, `docker_client.py`, minimal `main.py` + cog with `/vrising status` only
4. Write `Dockerfile`; bring up full stack; test status command end-to-end
5. Add `/vrising start` with auto-shutdown timer (including reschedule-if-running behavior)
6. Add `/vrising stop` with timer cancellation
7. Add `on_ready` startup check (schedule default timer if container already running)
8. Write `sync_commands.py`; run it to register guild commands and clear old satisfactory ones
9. Full integration test (see Verification below)

---

## Verification

**Proxy security:**

The bot image (python:3.14-slim) has no curl. Use a throwaway alpine/curl container on the same network:

```bash
# Inspect a container by name — expect 200
docker run --rm --network linkbot-discord_bot-internal alpine/curl \
  -s -o /dev/null -w "%{http_code}" \
  http://docker-proxy:2375/v1.55/containers/vrising11/json

# POST /containers/create — expect 403
docker run --rm --network linkbot-discord_bot-internal alpine/curl \
  -s -o /dev/null -w "%{http_code}" \
  -X POST http://docker-proxy:2375/v1.55/containers/create \
  -H 'Content-Type: application/json' -d '{}'

# Any unrelated endpoint (images) — expect 403
docker run --rm --network linkbot-discord_bot-internal alpine/curl \
  -s -o /dev/null -w "%{http_code}" \
  http://docker-proxy:2375/v1.55/images/json

# From host — expect connection refused (port not published)
curl http://localhost:2375/containers/json
```

**Bot behavior:**

- `/vrising status` → correct state (running or stopped)
- `/vrising start` → server starts, bot confirms with shutdown time
- `/vrising start` again (server already running) → timer rescheduled, no restart of container
- `/vrising start 2` → timer set to 2 hours
- `/vrising start 99` → rejected (exceeds MAX_SHUTDOWN_HOURS), helpful error message
- Wait for auto-shutdown (or temporarily shorten `DEFAULT_SHUTDOWN_HOURS` for testing) → server stops, bot posts to notification channel
- `/vrising start` → `/vrising stop` mid-timer → timer cancelled, no second stop attempt
- Restart bot while server running → `on_ready` schedules default timer, posts notice to channel
- Command from wrong guild (if testable) → silently ignored
