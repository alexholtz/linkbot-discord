import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


class QuietReconnectFilter(logging.Filter):
    """Collapse discord.py's reconnect traceback for transient network errors.

    discord.py logs every reconnect attempt with log.exception(), which dumps a
    full traceback even for a plain "network is down" DNS failure. During an
    outage that produces dozens of near-identical tracebacks. Errors that
    indicate a real problem (bad gateway response, auth failure, etc.) still
    keep their full traceback.
    """

    _TRANSIENT_EXCEPTIONS = (OSError, aiohttp.ClientError, asyncio.TimeoutError)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and isinstance(record.exc_info[1], self._TRANSIENT_EXCEPTIONS):
            exc = record.exc_info[1]
            record.msg = f"{record.getMessage()} ({type(exc).__name__}: {exc})"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


logging.getLogger("discord.client").addFilter(QuietReconnectFilter())

intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    vrising_cog = bot.cogs.get("vrising")
    if vrising_cog:
        await vrising_cog.check_startup_state()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """Ensure a slash command always gets a response, even on an unhandled error.

    Without this, an exception raised after interaction.response.defer() leaves
    the interaction stuck showing "thinking..." in Discord forever, since nothing
    ever calls followup.send() to resolve it.
    """
    log.exception(
        "Unhandled error in /%s",
        interaction.command.qualified_name if interaction.command else "?",
        exc_info=error,
    )
    message = "Something went wrong running that command."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


async def main() -> None:
    async with bot:
        await bot.load_extension("cogs.vrising")
        await bot.start(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
