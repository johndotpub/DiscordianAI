"""SRE-focused logging adapters for structured observability."""

import logging
from typing import Any

import discord


class ContextualLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that injects Discord context into log records.

    This ensures that every log record contains relevant ids like
    guild_id, channel_id, and user_id when available. Free text such as a
    guild name stays out of the log.
    """

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        """Process the log message and keyword arguments."""
        # Ensure 'extra' exists in kwargs
        if "extra" not in kwargs:
            kwargs["extra"] = {}

        # Merge our extra context into the log record's extra
        kwargs["extra"].update(self.extra)

        return msg, kwargs


def get_logger_with_context(
    logger: logging.Logger, message: discord.Message
) -> ContextualLoggerAdapter:
    """Create a LoggerAdapter with context extracted from a Discord message."""
    context = {
        "user_id": message.author.id,
        "channel_id": message.channel.id,
    }

    if message.guild:
        context["guild_id"] = message.guild.id

    return ContextualLoggerAdapter(logger, context)
