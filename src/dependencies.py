"""Formal dependency injection container for DiscordianAI.

Replaces the ad-hoc ``deps`` dictionary with a typed, frozen dataclass that
makes the bot's service graph explicit, prevents typos in key names, and
enables IDE autocompletion across the codebase.

Usage::

    from src.dependencies import BotDependencies

    deps = BotDependencies(
        bot=discord_client,
        logger=logger,
        config=config,
        ...
    )
"""

from __future__ import annotations

import asyncio  # noqa: TC003
from dataclasses import dataclass, field
import logging  # noqa: TC003
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .connection_pool import ConnectionPoolManager
    from .conversation_manager import ThreadSafeConversationManager
    from .health_server import HealthServer
    from .rate_limits import RateLimiter


@dataclass
class BotDependencies:
    """Typed dependency container for the DiscordianAI bot.

    All service objects and configuration needed by message handlers,
    health endpoints, and the bot lifecycle are wired through this
    dataclass instead of an untyped dict.

    Attributes:
        bot: The Discord client instance.
        logger: Root logger for the application.
        config: Full configuration dictionary.
        client: OpenAI AsyncClient (or ``None`` if not configured).
        perplexity_client: Perplexity AsyncClient (or ``None``).
        connection_pool_manager: HTTP connection pool manager.
        rate_limiter: Per-user rate limiter.
        conversation_manager: Thread-safe conversation history store.
        health_server: Health endpoint server (or ``None``).
        allowed_channels: List of channel IDs the bot responds in.
        bot_presence: Discord presence status string.
        activity_type: Discord activity type string.
        activity_status: Discord activity status text.
        discord_token: Discord bot authentication token.
        rate_limit: Maximum commands per user per window.
        rate_limit_period: Rate-limit window in seconds.
        gpt_model: OpenAI GPT model identifier.
        perplexity_model: Perplexity model identifier.
        system_message: System prompt for AI interactions.
        output_tokens: Maximum output tokens per response.
        health_task: Asyncio task for the health server (set at runtime).
    """

    # Service objects
    bot: Any
    logger: logging.Logger
    config: dict[str, Any]
    client: Any | None = None
    perplexity_client: Any | None = None
    connection_pool_manager: ConnectionPoolManager | None = None
    rate_limiter: RateLimiter | None = None
    conversation_manager: ThreadSafeConversationManager | None = None
    health_server: HealthServer | None = None

    # Configuration scalars (extracted from config for convenience)
    allowed_channels: list[int] = field(default_factory=list)
    bot_presence: str = "online"
    activity_type: str = "watching"
    activity_status: str = ""
    discord_token: str = ""
    rate_limit: int = 10
    rate_limit_period: int = 60
    gpt_model: str = "gpt-5-mini"
    perplexity_model: str = "sonar-pro"
    system_message: str = ""
    output_tokens: int = 8000

    # Runtime-only
    health_task: asyncio.Task | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a legacy deps dictionary for backward compatibility.

        This supports gradual migration: modules that haven't been updated
        to use the dataclass can still call ``deps.to_dict()`` to get the
        old-style dict.

        Returns:
            A dictionary with the same keys as the old ``deps`` dict.
        """
        return {
            "bot": self.bot,
            "logger": self.logger,
            "config": self.config,
            "client": self.client,
            "perplexity_client": self.perplexity_client,
            "connection_pool_manager": self.connection_pool_manager,
            "rate_limiter": self.rate_limiter,
            "conversation_manager": self.conversation_manager,
            "health_server": self.health_server,
            "ALLOWED_CHANNELS": self.allowed_channels,
            "BOT_PRESENCE": self.bot_presence,
            "ACTIVITY_TYPE": self.activity_type,
            "ACTIVITY_STATUS": self.activity_status,
            "DISCORD_TOKEN": self.discord_token,
            "RATE_LIMIT": self.rate_limit,
            "RATE_LIMIT_PER": self.rate_limit_period,
            "GPT_MODEL": self.gpt_model,
            "PERPLEXITY_MODEL": self.perplexity_model,
            "SYSTEM_MESSAGE": self.system_message,
            "OUTPUT_TOKENS": self.output_tokens,
            "_health_task": self.health_task,
        }

    def __getitem__(self, key: str) -> Any:
        """Support dict-style access for backward compatibility."""
        mapping = self.to_dict()
        return mapping[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Support dict-style writes for backward compatibility."""
        if key in self.to_dict():
            field_name = {
                "ALLOWED_CHANNELS": "allowed_channels",
                "BOT_PRESENCE": "bot_presence",
                "ACTIVITY_TYPE": "activity_type",
                "ACTIVITY_STATUS": "activity_status",
                "DISCORD_TOKEN": "discord_token",
                "RATE_LIMIT": "rate_limit",
                "RATE_LIMIT_PER": "rate_limit_period",
                "GPT_MODEL": "gpt_model",
                "PERPLEXITY_MODEL": "perplexity_model",
                "SYSTEM_MESSAGE": "system_message",
                "OUTPUT_TOKENS": "output_tokens",
                "_health_task": "health_task",
            }.get(key)
            if field_name:
                setattr(self, field_name, value)
            else:
                setattr(self, key, value)
        else:
            setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Support ``key in deps`` for backward compatibility."""
        return key in self.to_dict()

    def get(self, key: str, default: Any = None) -> Any:
        """Support ``deps.get(key, default)`` for backward compatibility."""
        return self.to_dict().get(key, default)
