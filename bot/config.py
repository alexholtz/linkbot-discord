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
TARGET_CONTAINER_NAME = _require("TARGET_CONTAINER_NAME")
NOTIFICATION_CHANNEL_ID = _require_int("NOTIFICATION_CHANNEL_ID")
DOCKER_PROXY_URL = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy:2375")
DEFAULT_SHUTDOWN_HOURS = int(os.getenv("DEFAULT_SHUTDOWN_HOURS", "6"))
MAX_SHUTDOWN_HOURS = int(os.getenv("MAX_SHUTDOWN_HOURS", "24"))
