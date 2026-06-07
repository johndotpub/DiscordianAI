"""Core message processing logic for AI response generation."""

import re
from typing import Any

import discord

from .error_handling import classify_error, safe_discord_send
from .logging_adapter import get_logger_with_context
from .message_splitter import clean_message_content, error_message, send_formatted_message
from .models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig
from .rate_limits import check_rate_limit
from .smart_orchestrator import get_smart_response


async def _process_message_core(
    message: discord.Message,
    deps: dict[str, Any] | Any,
    is_dm: bool = True,
) -> None:
    """Core message processing logic shared by DM and channel message handlers."""
    logger = get_logger_with_context(deps["logger"], message)
    rate_limiter = deps["rate_limiter"]
    conversation_manager = deps["conversation_manager"]
    clean_content = message.content

    # Prepare context-specific strings for logging and error messages
    if is_dm:
        rate_limit_msg = (
            "⏱️ Rate limit exceeded! Please wait a moment before sending another message."
        )
        error_msg = (
            "🔧 Sorry, I encountered an error while processing your message. "
            "Please try again in a moment."
        )
        display_content = clean_message_content(message.content, 100)
    else:
        # Clean message content for logging (remove mentions)
        clean_content = re.sub(r"<@\d+>", "", message.content).strip()
        logger.info(
            "Captured message for processing (ID: %s, length: %d)",
            message.id,
            len(clean_content),
        )
        rate_limit_msg = "⏱️ Rate limit exceeded! Please wait a moment before mentioning me again."
        error_msg = error_message(
            message.author.mention,
            "🔧 Sorry, I encountered an error while processing your message. "
            "Please try again in a moment.",
        )
        display_content = clean_message_content(clean_content, 100)

    try:
        logger.info("Processing message: %s", display_content)

        # Apply thread-safe rate limiting
        if not await check_rate_limit(
            message.author,
            rate_limiter,
            deps["RATE_LIMIT"],
            deps["RATE_LIMIT_PER"],
            logger,
        ):
            rate_msg = f"{message.author.mention} {rate_limit_msg}"
            if not await safe_discord_send(message.channel, rate_msg, logger):
                logger.error("Failed to send rate limit message")
            logger.warning("Rate limit exceeded")
            return

        # Get conversation summary using consolidated thread-safe manager
        conversation_summary = conversation_manager.get_conversation_summary_formatted(
            message.author.id,
        )

        # Initialize config objects
        openai_config = OpenAIConfig(
            model=deps["GPT_MODEL"],
            system_message=deps["SYSTEM_MESSAGE"],
            output_tokens=deps["OUTPUT_TOKENS"],
        )
        perplexity_model = (
            deps.get("PERPLEXITY_MODEL")
            or (deps.get("config") or {}).get("PERPLEXITY_MODEL")
            or "sonar-pro"
        )
        perplexity_config = PerplexityConfig(
            model=perplexity_model,
            system_message=deps["SYSTEM_MESSAGE"],
            output_tokens=deps["OUTPUT_TOKENS"],
        )
        ai_config = AIConfig(openai=openai_config, perplexity=perplexity_config)
        config = deps.get("config") or {}
        orchestrator_config = {
            key: config[key]
            for key in (
                "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
                "MAX_HISTORY_PER_USER",
                "USER_LOCK_CLEANUP_INTERVAL",
                "ENTITY_DETECTION_MIN_WORDS",
            )
            if key in config
        }

        # Create the unified AIRequest object
        request_message = message.content if is_dm else clean_content
        ai_request = AIRequest(
            message=request_message,
            user=message.author,
            conversation_manager=conversation_manager,
            logger=logger,
        )

        clients = AIClients(openai=deps.get("client"), perplexity=deps.get("perplexity_client"))

        # Generate AI response using smart orchestrator
        response, suppress_embeds, embed_data = await get_smart_response(
            ai_request,
            conversation_summary,
            clients,
            ai_config,
            orchestrator_config,
        )

        # Send response with automatic message splitting if needed
        await send_formatted_message(
            message.channel,
            response,
            deps,
            suppress_embeds=suppress_embeds,
            embed_data=embed_data,
            original_message=message,
            mention_prefix=f"{message.author.mention} ",
        )
        logger.info("Message processed and response sent")

    except Exception as e:
        logger.exception("Error processing message")

        # Classify error for better user messaging
        try:
            error_details = classify_error(e)
        except (AttributeError, TypeError):
            error_details = None
        user_friendly_msg = (
            error_details.user_message
            if (error_details is not None and hasattr(error_details, "user_message"))
            else error_msg
        )

        if not await safe_discord_send(message.channel, user_friendly_msg, logger):
            logger.error(  # noqa: TRY400 — intentional: exception already logged above
                "Failed to send error message"
            )


async def process_dm_message(message: discord.Message, deps: dict[str, Any] | Any) -> None:
    """Process direct messages with comprehensive error handling."""
    await _process_message_core(message, deps, is_dm=True)


async def process_channel_message(message: discord.Message, deps: dict[str, Any] | Any) -> None:
    """Process channel messages with comprehensive error handling."""
    await _process_message_core(message, deps, is_dm=False)
