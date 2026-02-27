"""Registry for Discord bot events."""

from typing import Any

import discord

from .logging_adapter import get_logger_with_context
from .message_processor import process_channel_message, process_dm_message


async def handle_incoming_message(
    message: discord.Message,
    deps: dict[str, Any],
    bot: discord.Client,
) -> None:
    """Handle incoming message with comprehensive routing and error handling."""
    logger = get_logger_with_context(deps["logger"], message)

    try:
        if message.author == bot.user:
            return

        if isinstance(message.channel, discord.DMChannel):
            await process_dm_message(message, deps)
            return

        if (
            isinstance(message.channel, discord.TextChannel)
            and message.channel.name in deps["ALLOWED_CHANNELS"]
            and bot.user in message.mentions
        ):
            await process_channel_message(message, deps)
            return

    except Exception:
        logger.exception("Unhandled error in message routing")
        try:
            if isinstance(message.channel, (discord.DMChannel, discord.TextChannel)):
                err_msg = "🔧 An unexpected error occurred. The issue has been logged."
                await message.channel.send(err_msg)
        except Exception:
            logger.exception("Failed to send error notification")
