import asyncio
import logging

import discord
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

intents = discord.Intents(guilds=True)
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    vrising_cog = bot.cogs.get("vrising")
    if vrising_cog:
        await vrising_cog.check_startup_state()


async def main() -> None:
    async with bot:
        await bot.load_extension("cogs.vrising")
        await bot.start(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
