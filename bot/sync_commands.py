"""
One-shot script to register slash commands with Discord.

Run after first deploy and whenever commands change:
    docker compose run --rm bot python sync_commands.py

This will:
  - Clear all global commands (removes any old /satisfactory commands)
  - Sync guild-specific commands to DISCORD_GUILD_ID
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

    # Wipe global commands (catches any old /satisfactory or other leftovers)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print("Cleared all global commands.")

    # Sync guild commands
    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} command(s) to guild {config.DISCORD_GUILD_ID}:")
    for cmd in synced:
        print(f"  /{cmd.name}")

    await bot.close()


asyncio.run(main())
