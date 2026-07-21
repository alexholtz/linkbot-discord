"""
One-shot script to register slash commands with Discord.

Run after first deploy and whenever command signatures change:
    docker exec linkbot-discord-bot-1 python sync_commands.py
"""

import asyncio
import discord
from discord.ext import commands
import config


async def main() -> None:
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)

    await bot.load_extension("cogs.vrising")
    await bot.login(config.DISCORD_BOT_TOKEN)

    guild = discord.Object(id=config.DISCORD_GUILD_ID)

    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} command(s) to guild {config.DISCORD_GUILD_ID}:")
    for cmd in synced:
        print(f"  /{cmd.name}")

    await bot.close()


asyncio.run(main())
