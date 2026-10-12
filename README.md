# linkbot-discord

Discord bot (LinkBot, named after a beloved companion) that controls game server containers (V Rising, Factorio) on a Synology NAS via slash commands.

## Architecture

Two containers on an isolated internal network:

- **bot** — Python discord.py bot, handles slash commands
- **docker-proxy** — custom haproxy that gates access to the Docker socket; allows only container inspect, start, and stop — blocks everything else including container creation

The bot never touches the Docker socket directly.

## Commands

Each enabled game gets the same command group (`/vrising`, `/factorio`):

| Command | Description |
|---|---|
| `/<game> start [hours]` | Start the server; arms auto-shutdown timer (default: `DEFAULT_SHUTDOWN_HOURS`) |
| `/<game> stop [force]` | Stop the server and cancel the timer; aborts if players are online unless `force` is passed |
| `/<game> status` | Show server state, player count, and time remaining until auto-shutdown |

If the server is already running when `start` is called, the timer is rescheduled
without restarting the container. On bot restart, any game server found running gets a default
timer armed automatically. When the timer fires with players still online, shutdown is
postponed 1h at a time.

## Games

The shared start/stop/status and auto-shutdown logic lives in `bot/cogs/game_server.py`
(`GameServerCog`). Each game is a small subclass that supplies its container name and how to
count players / announce in-game:

| Game | Player count | Announce | Before stop |
|---|---|---|---|
| V Rising (`cogs/vrising.py`) | metrics API (`vr_users_connected`) | RCON `announce` | -- |
| Factorio (`cogs/factorio.py`) | RCON `/players online` | RCON chat message | RCON `/server-save`, then waits 10s |

Factorio note: never send Lua commands (`/c`, `/silent-command`) over RCON -- they permanently
disable achievements for the save.

To add a game: subclass `GameServerCog`, add its env vars to `config.py`, and add its
extension to `GAME_EXTENSIONS`.

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
DISCORD_BOT_TOKEN=        # bot token from Discord developer portal
DISCORD_GUILD_ID=         # your server's ID
NOTIFICATION_CHANNEL_ID=  # channel where auto-shutdown notices are posted
DEFAULT_SHUTDOWN_HOURS=6  # default timer duration
MAX_SHUTDOWN_HOURS=24     # upper bound for user-supplied duration

VRISING_CONTAINER_NAME=   # exact Docker container name; blank disables /vrising
FACTORIO_CONTAINER_NAME=  # exact Docker container name; blank disables /factorio
```

Plus optional per-game metrics/RCON settings (`VRISING_METRICS_URL`, `VRISING_RCON_*`,
`FACTORIO_RCON_*`) -- see `.env.example`.

## Deployment (Synology NAS)

```bash
# One-time setup
ssh you@nas
git clone <repo-url> ~/docker/linkbot-discord
cd ~/docker/linkbot-discord
cp .env.example .env
nano .env
docker compose up -d --build

# Register slash commands
docker exec linkbot-discord-bot-1 python sync_commands.py

# Updates
git pull && docker compose up -d --build
```

### Syncing slash commands

`sync_commands.py` runs inside the already-running bot container, so it uses that
container's code and `.env`. Always rebuild/recreate first (`docker compose up -d --build`),
then sync -- otherwise it registers the old command set.

Re-run the sync when:
- a game is enabled or disabled (its `<GAME>_CONTAINER_NAME` set or cleared in `.env`)
- a command's name, options, or description changes

Changes to command behavior only need the rebuild. A successful sync prints each registered
group, e.g. `/vrising` and `/factorio`.

## Troubleshooting

If `.env` is missing a required value, has a non-numeric value where a number is expected,
or Discord rejects the token, the bot logs the error once and halts instead of crash-looping.
The container stays up but shows as **unhealthy** in `docker ps` / Container Manager.
Check `docker compose logs bot`, fix `.env`, then `docker compose up -d` (a plain
`restart` won't pick up `.env` changes).

## Useful Compose Commands

```bash
# Stop containers (keeps them, can be restarted quickly)
docker compose stop

# Stop and remove containers + networks (clean slate)
docker compose down

# View live logs
docker compose logs -f

# Restart a single service after a code change
docker compose restart bot
```

## Local Development

A test container (fake vRising target) is available via the `test` profile:

```bash
docker compose --profile test up -d
```

Set `VRISING_CONTAINER_NAME` in `.env` to match `container_name` in the `test-server` service.

### Verify proxy security

```bash
# Inspect — expect 200
docker run --rm --network linkbot-discord_bot-internal alpine/curl \
  -s -o /dev/null -w "%{http_code}" \
  http://docker-proxy:2375/v1.55/containers/<container-name>/json

# Container create — expect 403
docker run --rm --network linkbot-discord_bot-internal alpine/curl \
  -s -o /dev/null -w "%{http_code}" \
  -X POST http://docker-proxy:2375/v1.55/containers/create \
  -H 'Content-Type: application/json' -d '{}'
```
