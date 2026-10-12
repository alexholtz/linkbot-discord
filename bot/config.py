import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def _require_int(name: str) -> int:
    value = _require(name)
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(
            f"Environment variable {name!r} must be an integer, got {value!r}"
        )


DISCORD_BOT_TOKEN = _require("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = _require_int("DISCORD_GUILD_ID")
NOTIFICATION_CHANNEL_ID = _require_int("NOTIFICATION_CHANNEL_ID")
DOCKER_PROXY_URL = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy:2375")
DEFAULT_SHUTDOWN_HOURS = int(os.getenv("DEFAULT_SHUTDOWN_HOURS", "6"))
MAX_SHUTDOWN_HOURS = int(os.getenv("MAX_SHUTDOWN_HOURS", "24"))

# Each game is enabled by setting its container name; its cog is skipped otherwise.
# Metrics/RCON are optional -- if unset, player counts and announces are skipped gracefully.

# V Rising
VRISING_CONTAINER_NAME: str | None = os.getenv("VRISING_CONTAINER_NAME")
VRISING_METRICS_URL: str | None = os.getenv("VRISING_METRICS_URL")
VRISING_RCON_HOST: str | None = os.getenv("VRISING_RCON_HOST")
VRISING_RCON_PORT: int = int(os.getenv("VRISING_RCON_PORT", "25575"))
VRISING_RCON_PASSWORD: str | None = os.getenv("VRISING_RCON_PASSWORD")

# Factorio
FACTORIO_CONTAINER_NAME: str | None = os.getenv("FACTORIO_CONTAINER_NAME")
FACTORIO_RCON_HOST: str | None = os.getenv("FACTORIO_RCON_HOST")
FACTORIO_RCON_PORT: int = int(os.getenv("FACTORIO_RCON_PORT", "27015"))
FACTORIO_RCON_PASSWORD: str | None = os.getenv("FACTORIO_RCON_PASSWORD")

GAME_EXTENSIONS: list[str] = [
    ext
    for ext, container in (
        ("cogs.vrising", VRISING_CONTAINER_NAME),
        ("cogs.factorio", FACTORIO_CONTAINER_NAME),
    )
    if container
]
if not GAME_EXTENSIONS:
    raise RuntimeError(
        "No games enabled -- set at least one of VRISING_CONTAINER_NAME, FACTORIO_CONTAINER_NAME"
    )
