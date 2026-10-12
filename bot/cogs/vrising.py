import asyncio
import logging
import urllib.request

import discord
from discord.ext import commands

import config
import rcon
from cogs.game_server import GameServerCog

log = logging.getLogger(__name__)


class VRising(GameServerCog, name="vrising", description="V Rising server controls"):
    display_name = "V Rising"
    container_name = config.VRISING_CONTAINER_NAME

    @property
    def player_count_enabled(self) -> bool:
        return bool(config.VRISING_METRICS_URL)

    async def get_player_count(self) -> int | None:
        return await asyncio.to_thread(self._fetch_users_connected)

    async def announce(self, message: str) -> None:
        if not (config.VRISING_RCON_HOST and config.VRISING_RCON_PASSWORD):
            return
        try:
            await rcon.send_command(
                config.VRISING_RCON_HOST,
                config.VRISING_RCON_PORT,
                config.VRISING_RCON_PASSWORD,
                f"announce {message}",
            )
        except Exception as e:
            log.warning("RCON announce failed: %s", e)

    def _fetch_users_connected(self) -> int | None:
        """Fetch vr_users_connected from the metrics API. Returns None on failure."""
        try:
            with urllib.request.urlopen(config.VRISING_METRICS_URL, timeout=5) as resp:
                for line in resp.read().decode().splitlines():
                    if line.startswith("vr_users_connected "):
                        return int(float(line.split()[1]))
            log.warning("vr_users_connected not found in metrics response")
        except Exception as e:
            log.warning("Failed to fetch metrics: %s", e)
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        VRising(bot),
        guilds=[discord.Object(id=config.DISCORD_GUILD_ID)],
    )
