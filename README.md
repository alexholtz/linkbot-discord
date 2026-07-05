# linkbot-discord

Discord bot (LinkBot, named after a beloved companion) that controls a V Rising game server container on a Synology NAS via slash commands.

## Architecture

Two containers on an isolated internal network:

- **bot** — Python discord.py bot, handles slash commands
- **docker-proxy** — custom haproxy that gates access to the Docker socket; allows only container inspect, start, and stop — blocks everything else including container creation

The bot never touches the Docker socket directly.

## Commands

| Command | Description |
|---|---|
| `/vrising start [hours]` | Start the server; arms auto-shutdown timer (default: `DEFAULT_SHUTDOWN_HOURS`) |
| `/vrising stop` | Stop the server and cancel the timer |
| `/vrising status` | Show server state and time remaining until auto-shutdown |

If the server is already running when `/vrising start` is called, the timer is rescheduled
without restarting the container. On bot restart, if the server is found running, a default
timer is armed automatically.

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
DISCORD_BOT_TOKEN=        # bot token from Discord developer portal
DISCORD_GUILD_ID=         # your server's ID
TARGET_CONTAINER_NAME=    # exact Docker container name of the vRising server
NOTIFICATION_CHANNEL_ID=  # channel where auto-shutdown notices are posted
DEFAULT_SHUTDOWN_HOURS=6  # default timer duration
MAX_SHUTDOWN_HOURS=24     # upper bound for user-supplied duration
```

## Deployment (Synology NAS)

```bash
# One-time setup
ssh you@nas
git clone <repo-url> ~/docker/linkbot-discord
cd ~/docker/linkbot-discord
cp .env.example .env
nano .env
docker compose up -d --build

# Register slash commands (once, or after command changes)
docker compose run --rm bot python sync_commands.py

# Updates
git pull && docker compose up -d --build
```

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

Set `TARGET_CONTAINER_NAME` in `.env` to match `container_name` in the `test-server` service.

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
