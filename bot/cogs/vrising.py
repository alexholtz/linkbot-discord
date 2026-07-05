import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
import docker_client
import docker.errors

log = logging.getLogger(__name__)


class VRising(commands.GroupCog, name="vrising"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._shutdown_task: asyncio.Task | None = None
        self._shutdown_at: datetime | None = None
        super().__init__()

    def _wrong_guild(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id != config.DISCORD_GUILD_ID

    @app_commands.command(name="start", description="Start the V Rising server")
    @app_commands.describe(hours="Hours until auto-shutdown (default from config)")
    async def start(
        self, interaction: discord.Interaction, hours: int | None = None
    ) -> None:
        if self._wrong_guild(interaction):
            return

        hours = hours if hours is not None else config.DEFAULT_SHUTDOWN_HOURS

        if not (1 <= hours <= config.MAX_SHUTDOWN_HOURS):
            await interaction.response.send_message(
                f"Hours must be between 1 and {config.MAX_SHUTDOWN_HOURS}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            status = await asyncio.to_thread(docker_client.container_status)
        except Exception as e:
            await interaction.followup.send(f"Could not reach Docker proxy: {e}")
            return

        already_running = status == "running"

        if not already_running:
            try:
                await asyncio.to_thread(docker_client.start_container)
            except Exception as e:
                await interaction.followup.send(f"Failed to start server: {e}")
                return

        self._reschedule(hours)

        shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
        if already_running:
            msg = f"Fetch was already going — reset the timer to **{hours}h** (at {shutdown_ts})."
        else:
            msg = f"Let's play fetch! Server starting up. Auto-shutdown in **{hours}h** (at {shutdown_ts})."

        await interaction.followup.send(msg)

    @app_commands.command(name="stop", description="Stop the V Rising server")
    async def stop(self, interaction: discord.Interaction) -> None:
        if self._wrong_guild(interaction):
            return

        await interaction.response.defer()

        self._cancel_shutdown()

        try:
            await asyncio.to_thread(docker_client.stop_container)
            await interaction.followup.send("Playtime is over. Server stopped.")
        except Exception as e:
            await interaction.followup.send(f"Failed to stop server: {e}")

    @app_commands.command(name="status", description="Check the V Rising server status")
    async def status(self, interaction: discord.Interaction) -> None:
        if self._wrong_guild(interaction):
            return

        status = await asyncio.to_thread(docker_client.container_status)

        if status == "running":
            if self._shutdown_at:
                remaining = self._shutdown_at - datetime.now(timezone.utc)
                total_secs = max(int(remaining.total_seconds()), 0)
                h, rem = divmod(total_secs, 3600)
                m = rem // 60
                shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
                msg = f"Server is **running**. Auto-shutdown in {h}h {m}m (at {shutdown_ts})."
            else:
                msg = "Server is **running**. No auto-shutdown scheduled."
        else:
            msg = "Server is **offline**."

        await interaction.response.send_message(msg)

    async def check_startup_state(self) -> None:
        """Called from on_ready: if the container is already running, arm a default timer."""
        status = await asyncio.to_thread(docker_client.container_status)
        if status != "running":
            return

        hours = config.DEFAULT_SHUTDOWN_HOURS
        log.warning(
            "V Rising container found running at startup — scheduling %dh auto-shutdown", hours
        )
        self._reschedule(hours)

        channel = await self._notification_channel()
        if channel:
            shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
            await channel.send(
                f"Woke up from a nap (restarted) — V Rising was already running! "
                f"Auto-shutdown in **{hours}h** (at {shutdown_ts})."
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _reschedule(self, hours: int) -> None:
        self._cancel_shutdown()
        self._shutdown_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        self._shutdown_task = asyncio.create_task(self._auto_shutdown(hours))

    def _cancel_shutdown(self) -> None:
        if self._shutdown_task and not self._shutdown_task.done():
            self._shutdown_task.cancel()
        self._shutdown_task = None
        self._shutdown_at = None

    async def _auto_shutdown(self, hours: int) -> None:
        try:
            await asyncio.sleep(hours * 3600)
        except asyncio.CancelledError:
            return

        log.info("Auto-shutdown timer fired — stopping V Rising container")
        try:
            await asyncio.to_thread(docker_client.stop_container)
        except Exception as e:
            log.error("Auto-shutdown failed to stop container: %s", e)

        self._shutdown_task = None
        self._shutdown_at = None

        channel = await self._notification_channel()
        if channel:
            await channel.send("I'm tired (auto-shutdown) — server stopped.")

    async def _notification_channel(
        self,
    ) -> discord.TextChannel | None:
        channel = self.bot.get_channel(config.NOTIFICATION_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(config.NOTIFICATION_CHANNEL_ID)
            except discord.errors.NotFound:
                log.error(
                    "Notification channel %d not found", config.NOTIFICATION_CHANNEL_ID
                )
        return channel


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        VRising(bot),
        guilds=[discord.Object(id=config.DISCORD_GUILD_ID)],
    )
