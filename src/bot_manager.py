"""Discord bot manager class for handling bot lifecycle and events."""

import asyncio
import signal
from typing import Any

import discord

from .discord_bot import set_activity_status
from .health_checks import APIHealthMonitor
from .message_router import handle_incoming_message


class DiscordBotManager:
    """Manages Discord bot lifecycle, event registration, and state."""

    def __init__(self, deps: dict[str, Any]):
        """Initialize the bot manager with dependencies."""
        self.deps = deps
        self.bot = deps["bot"]
        self.logger = deps["logger"]
        self.config = deps["config"]

    def register_events(self):
        """Register all Discord event handlers."""

        @self.bot.event
        async def on_ready():
            self.logger.info(
                "Bot logged in as %s (ID: %s)",
                self.bot.user.name,
                self.bot.user.id,
            )
            self.logger.info("Connected to %d servers", len(self.bot.guilds))

            # Set presence
            activity = set_activity_status(
                self.deps["ACTIVITY_TYPE"],
                self.deps["ACTIVITY_STATUS"],
            )
            await self.bot.change_presence(
                activity=activity,
                status=discord.Status(self.deps["BOT_PRESENCE"]),
            )

            # Schedule health checks
            self.logger.info("Initiating health monitoring...")
            health_monitor = APIHealthMonitor()
            clients_for_health_check = {
                "openai": self.deps.get("client"),
                "perplexity": self.deps.get("perplexity_client"),
            }
            self.deps["_health_task"] = asyncio.create_task(
                health_monitor.run_all_health_checks(clients_for_health_check, self.config),
            )
            self.logger.info("Bot ready to process messages")

        @self.bot.event
        async def on_message(message: discord.Message):
            # Handled by message router
            await handle_incoming_message(message, self.deps, self.bot)

        @self.bot.event
        async def on_disconnect():
            self.logger.warning("Bot has disconnected from Discord")

        @self.bot.event
        async def on_resumed():
            self.logger.info("Bot connection resumed successfully")

    async def graceful_shutdown(self):
        """Perform graceful shutdown of the bot and cleanup resources."""
        self.logger.info("Initiating graceful shutdown...")

        if not self.bot.is_closed():
            await self.bot.close()
            self.logger.info("Discord connection closed")

        if "connection_pool_manager" in self.deps:
            pool_manager = self.deps["connection_pool_manager"]
            if hasattr(pool_manager, "close_all"):
                await pool_manager.close_all()
                self.logger.info("Connection pools closed")

        if "_health_task" in self.deps:
            health_task = self.deps["_health_task"]
            if not health_task.done():
                health_task.cancel()

            try:
                await health_task
            except asyncio.CancelledError:
                self.logger.info("Health monitoring task cancelled")
            except Exception:
                self.logger.exception("Health monitoring task raised during shutdown")
            else:
                self.logger.info("Health monitoring task completed")

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum, _frame):
            self.logger.info("Received signal %s, initiating graceful shutdown...", signum)
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def run(self):
        """Start the bot."""
        self.register_events()
        self.setup_signal_handlers()
        try:
            self.bot.run(self.deps["DISCORD_TOKEN"])
        except KeyboardInterrupt:
            self.logger.info("Bot interrupted by user, shutting down...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.graceful_shutdown())
            finally:
                loop.close()
