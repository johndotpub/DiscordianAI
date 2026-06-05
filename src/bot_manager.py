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

    def __init__(self, deps: dict[str, Any] | Any):
        """Initialize the bot manager with dependencies."""
        self.deps = deps
        self.bot = deps["bot"]
        self.logger = deps["logger"]
        self.config = deps["config"]
        self._shutdown_requested = False
        self._running = False
        self._bot_loop: asyncio.AbstractEventLoop | None = None

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
            self.logger.info("Initiating health monitoring")
            health_monitor = APIHealthMonitor()
            clients_for_health_check = {
                "openai": self.deps.get("client"),
                "perplexity": self.deps.get("perplexity_client"),
            }
            self.deps["_health_task"] = asyncio.create_task(
                health_monitor.run_all_health_checks(clients_for_health_check, self.config),
            )
            self.logger.info("Bot ready to process messages")

            # Start the health server after bot is ready
            health_server = self.deps.get("health_server")
            if health_server:
                await health_server.start()

        @self.bot.event
        async def on_message(message: discord.Message):
            # Handled by message router
            await handle_incoming_message(message, self.deps, self.bot)

        @self.bot.event
        async def on_disconnect():
            self.logger.warning("Bot disconnected from Discord")

        @self.bot.event
        async def on_resumed():
            self.logger.info("Bot connection resumed")

    async def graceful_shutdown(self):
        """Perform graceful shutdown of the bot and cleanup resources."""
        self.logger.info("Initiating graceful shutdown")

        # Stop health server first
        health_server = self.deps.get("health_server")
        if health_server:
            await health_server.stop()

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
            if self._shutdown_requested:
                return

            self._shutdown_requested = True
            self.logger.info("Received signal %s, shutting down", signum)

            loop = getattr(self.bot, "loop", None)
            if loop and not loop.is_closed():
                loop.call_soon_threadsafe(loop.create_task, self.graceful_shutdown())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def run(self):
        """Start the bot."""
        if self._running:
            self.logger.error("Bot manager run() called while already running")
            return

        self.register_events()
        self.setup_signal_handlers()
        try:
            self._running = True
            try:
                self._bot_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._bot_loop = getattr(self.bot, "loop", None)
            self.bot.run(self.deps["DISCORD_TOKEN"], log_handler=None)
        except KeyboardInterrupt:
            if not self._shutdown_requested:
                self.logger.info("Bot interrupted by user, shutting down")
            try:
                if self._bot_loop and not self._bot_loop.is_closed():
                    self._bot_loop.run_until_complete(self.graceful_shutdown())
                else:
                    self.logger.warning("Bot loop unavailable; creating fallback shutdown loop")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.graceful_shutdown())
                    finally:
                        loop.close()
            finally:
                self._running = False
        finally:
            self._running = False
