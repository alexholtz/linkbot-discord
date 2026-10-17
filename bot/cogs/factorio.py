import asyncio
import logging
import re

import discord
from discord.ext import commands

import config
import rcon
from cogs.game_server import GameServerCog

log = logging.getLogger(__name__)

# `/players online` replies with e.g. "Online players (2):\n  alex (online)\n  ..."
_ONLINE_PLAYERS_RE = re.compile(r"Online players \((\d+)\)")

# /server-save returns before the write finishes; give it time before the container stops.
_SAVE_WAIT_SECONDS = 10

# Never send Lua (/c, /silent-command) over RCON: it permanently disables achievements on the save.


class Factorio(GameServerCog, name="factorio", description="Factorio server controls"):
    display_name = "Factorio"
    container_name = config.FACTORIO_CONTAINER_NAME

    @property
    def player_count_enabled(self) -> bool:
        return self._rcon_configured

    @property
    def _rcon_configured(self) -> bool:
        return bool(config.FACTORIO_RCON_HOST and config.FACTORIO_RCON_PASSWORD)

    async def _rcon(self, command: str) -> str:
        return await rcon.send_command(
            config.FACTORIO_RCON_HOST,
            config.FACTORIO_RCON_PORT,
            config.FACTORIO_RCON_PASSWORD,
            command,
        )

    async def get_player_count(self) -> int | None:
        try:
            response = await self._rcon("/players online")
        except Exception as e:
            log.warning("Failed to fetch Factorio player count: %s", e)
            return None
        match = _ONLINE_PLAYERS_RE.search(response)
        if not match:
            log.warning("Unexpected /players online response: %r", response)
            return None
        return int(match.group(1))

    async def announce(self, message: str) -> None:
        if not self._rcon_configured:
            return
        try:
            # Text without a leading slash is posted to chat as <server>.
            await self._rcon(message)
        except Exception as e:
            log.warning("RCON announce failed: %s", e)

    async def before_stop(self) -> None:
        if not self._rcon_configured:
            return
        try:
            await self._rcon("/server-save")
        except Exception as e:
            log.warning("RCON /server-save failed (server may not be running): %s", e)
            return
        await asyncio.sleep(_SAVE_WAIT_SECONDS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Factorio(bot),
        guilds=[discord.Object(id=config.DISCORD_GUILD_ID)],
    )
