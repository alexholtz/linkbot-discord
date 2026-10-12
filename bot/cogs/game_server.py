import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

import config
import docker_client

log = logging.getLogger(__name__)


class GameServerCog(commands.GroupCog):
    """Shared /<game> start|stop|status commands and player-aware auto-shutdown.

    Subclasses set the class attributes below and implement the player-count /
    announce hooks for their game. Pass the slash command group name as the
    class kwarg, e.g. `class Factorio(GameServerCog, name="factorio")`.
    """

    display_name: str
    container_name: str

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._shutdown_task: asyncio.Task | None = None
        self._shutdown_at: datetime | None = None
        super().__init__()

    # ------------------------------------------------------------------ #
    # Game-specific hooks                                                  #
    # ------------------------------------------------------------------ #

    @property
    def player_count_enabled(self) -> bool:
        """Whether this game is configured to report a player count."""
        return False

    async def get_player_count(self) -> int | None:
        """Number of connected players, or None if it couldn't be fetched."""
        return None

    async def announce(self, message: str) -> None:
        """Broadcast a message in-game. Should log and swallow errors."""

    async def before_stop(self) -> None:
        """Runs before every container stop (manual or auto). Should log and swallow errors."""

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    def _wrong_guild(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id != config.DISCORD_GUILD_ID

    @app_commands.command(name="start", description="Start the server")
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
            status = await asyncio.to_thread(docker_client.container_status, self.container_name)
        except Exception as e:
            await interaction.followup.send(f"Could not reach Docker proxy: {e}")
            return

        already_running = status == "running"

        if not already_running:
            try:
                await asyncio.to_thread(docker_client.start_container, self.container_name)
            except Exception as e:
                await interaction.followup.send(f"Failed to start server: {e}")
                return

        self._reschedule(hours)

        shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
        if already_running:
            msg = f"Fetch was already going -- reset the timer to **{hours}h** (at {shutdown_ts})."
        else:
            msg = f"Let's play fetch! {self.display_name} server starting up. Auto-shutdown in **{hours}h** (at {shutdown_ts})."

        await interaction.followup.send(msg)

    @app_commands.command(name="stop", description="Stop the server")
    @app_commands.describe(force="Pass 'force' to stop even if players are online")
    async def stop(
        self, interaction: discord.Interaction, force: Literal["force"] | None = None
    ) -> None:
        if self._wrong_guild(interaction):
            return

        await interaction.response.defer()

        if force != "force" and self.player_count_enabled:
            connected = await self.get_player_count()
            if connected is not None and connected > 0:
                await interaction.followup.send(
                    f"Can't stop -- **{connected}** player(s) are online. "
                    f"Use `/{self.qualified_name} stop force:force` to stop anyway."
                )
                return

        self._cancel_shutdown()

        try:
            await self._stop_server()
            await interaction.followup.send("Playtime is over. Server stopped.")
        except Exception as e:
            await interaction.followup.send(f"Failed to stop server: {e}")

    @app_commands.command(name="status", description="Check the server status")
    async def status(self, interaction: discord.Interaction) -> None:
        if self._wrong_guild(interaction):
            return

        try:
            status = await asyncio.to_thread(docker_client.container_status, self.container_name)
        except Exception as e:
            await interaction.response.send_message(
                f"Could not reach Docker proxy: {e}", ephemeral=True
            )
            return

        if status == "running":
            # Defer first: an RCON/metrics timeout could exceed Discord's 3s response window.
            await interaction.response.defer()
            connected = await self.get_player_count() if self.player_count_enabled else None
            player_str = f" | **{connected}** player(s) online" if connected is not None else ""

            if self._shutdown_at:
                remaining = self._shutdown_at - datetime.now(timezone.utc)
                total_secs = max(int(remaining.total_seconds()), 0)
                h, rem = divmod(total_secs, 3600)
                m = rem // 60
                shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
                msg = f"{self.display_name} is **running**{player_str}. Auto-shutdown in {h}h {m}m (at {shutdown_ts})."
            else:
                msg = f"{self.display_name} is **running**{player_str}. No auto-shutdown scheduled."
            await interaction.followup.send(msg)
        else:
            await interaction.response.send_message(f"{self.display_name} is **offline**.")

    async def check_startup_state(self) -> None:
        """Called from on_ready: if the container is already running, arm a default timer."""
        status = await asyncio.to_thread(docker_client.container_status, self.container_name)
        if status != "running":
            return

        hours = config.DEFAULT_SHUTDOWN_HOURS
        log.warning(
            "%s container found running at startup -- scheduling %dh auto-shutdown",
            self.display_name,
            hours,
        )
        self._reschedule(hours)

        channel = await self._notification_channel()
        if channel:
            shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
            await channel.send(
                f"Woke up from a nap (restarted) -- {self.display_name} was already running! "
                f"Auto-shutdown in **{hours}h** (at {shutdown_ts})."
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _stop_server(self) -> None:
        await self.before_stop()
        await asyncio.to_thread(docker_client.stop_container, self.container_name)

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
            while True:
                await asyncio.sleep(hours * 3600)

                if not self.player_count_enabled:
                    break  # player count not configured -- shut down as scheduled

                connected = await self.get_player_count()

                if connected is None:
                    # Configured but fetch failed -- extend to avoid surprise shutdown
                    log.warning(
                        "%s player count unavailable at shutdown check -- extending 1h",
                        self.display_name,
                    )
                    hours = 1
                    self._shutdown_at = datetime.now(timezone.utc) + timedelta(hours=1)
                    await self.announce(
                        "Server auto-shutdown postponed -- couldn't verify player count. Checking again in 1h."
                    )
                    channel = await self._notification_channel()
                    if channel:
                        shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
                        await channel.send(
                            f"⚠️ Couldn't get the {self.display_name} player count at shutdown time -- extended **1h** to be safe (next check at {shutdown_ts})."
                        )
                elif connected > 0:
                    log.info(
                        "%s auto-shutdown check: %d player(s) online -- extending 1h",
                        self.display_name,
                        connected,
                    )
                    hours = 1
                    self._shutdown_at = datetime.now(timezone.utc) + timedelta(hours=1)
                    await self.announce(
                        f"Server auto-shutdown postponed -- {connected} player(s) still online. Checking again in 1h."
                    )
                    channel = await self._notification_channel()
                    if channel:
                        shutdown_ts = discord.utils.format_dt(self._shutdown_at, style="t")
                        await channel.send(
                            f"**{connected}** player(s) still on {self.display_name} at shutdown time -- extended **1h** (next check at {shutdown_ts})."
                        )
                else:
                    break  # 0 players -- proceed to shutdown

        except asyncio.CancelledError:
            return

        log.info("Auto-shutdown timer fired -- stopping %s container", self.display_name)
        try:
            await self._stop_server()
        except Exception as e:
            log.error("Auto-shutdown failed to stop %s container: %s", self.display_name, e)

        self._shutdown_task = None
        self._shutdown_at = None

        channel = await self._notification_channel()
        if channel:
            await channel.send(f"I'm tired (auto-shutdown) -- {self.display_name} server stopped.")

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
