# Standard library imports
import asyncio
import logging
import re
from typing import Any

# Third-party imports
import discord
from openai import OpenAI

from .conversation_manager import ThreadSafeConversationManager
from .discord_bot import set_activity_status
from .discord_embeds import citation_embed_formatter
from .error_handling import classify_error, safe_discord_send
from .health_checks import APIHealthMonitor
from .message_utils import (
    MessageFormatter,
    adjust_split_for_code_blocks,
    clean_message_content,
    find_optimal_split_point,
)
from .rate_limits import RateLimiter, check_rate_limit
from .smart_orchestrator import get_smart_response


def initialize_bot_and_dependencies(config: dict[str, Any]) -> dict[str, Any]:
    """Initialize Discord bot and all required dependencies with comprehensive error handling.

    This function sets up the Discord client, API clients (OpenAI and Perplexity),
    logging, rate limiting, and conversation management in a production-ready manner.

    Args:
        config (Dict[str, Any]): Configuration dictionary containing all bot settings
                                including API keys, Discord settings, and operational parameters.

    Returns:
        Dict[str, Any]: Dependency injection container with all initialized components:
            - logger: Configured logger instance
            - bot: Discord client with appropriate intents
            - client: OpenAI client (None if OPENAI_API_KEY not provided)
            - perplexity_client: Perplexity client (None if PERPLEXITY_API_KEY not provided)
            - rate_limiter: Thread-safe rate limiting instance
            - conversation_manager: Thread-safe conversation history manager
            - Various configuration values for runtime use

    Raises:
        ValueError: If critical configuration is missing or invalid
        Exception: If client initialization fails
    """
    logger = logging.getLogger("discordianai.bot")
    logger.setLevel(getattr(logging, config["LOG_LEVEL"].upper(), logging.INFO))

    # Configure Discord intents for optimal performance
    intents = discord.Intents.default()
    intents.typing = False  # Disable typing indicators to reduce noise
    intents.presences = False  # Disable presence updates for better performance
    bot = discord.Client(intents=intents)

    # Initialize OpenAI client if API key is provided
    client = None
    if config["OPENAI_API_KEY"]:
        try:
            client = OpenAI(api_key=config["OPENAI_API_KEY"], base_url=config["OPENAI_API_URL"])
            logger.info(
                f"OpenAI client initialized successfully with model: {config['GPT_MODEL']}"
            )
        except Exception as e:
            logger.exception("Failed to initialize OpenAI client")
            raise RuntimeError("OpenAI client initialization failed") from e
    else:
        logger.info("No OpenAI API key provided - GPT models disabled")

    # Initialize Perplexity client for web search if API key is provided
    perplexity_client = None
    if config["PERPLEXITY_API_KEY"]:
        try:
            perplexity_client = OpenAI(
                api_key=config["PERPLEXITY_API_KEY"], base_url=config["PERPLEXITY_API_URL"]
            )
            logger.info("Perplexity client initialized successfully for web search")
        except Exception as e:
            logger.exception("Failed to initialize Perplexity client")
            raise RuntimeError("Perplexity client initialization failed") from e
    else:
        logger.info("No Perplexity API key provided - web search disabled")

    # Verify at least one API is configured
    if not client and not perplexity_client:
        error_msg = (
            "No API keys provided! Bot cannot function without either OpenAI or "
            "Perplexity API access. Please provide either OPENAI_API_KEY (for OpenAI) or "
            "PERPLEXITY_API_KEY (for Perplexity) or both."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    if client and perplexity_client:
        logger.info(
            "Running in HYBRID mode (OpenAI + Perplexity) - Smart AI orchestration enabled"
        )
    elif client:
        logger.info("Running in OpenAI-only mode")
    elif perplexity_client:
        logger.info("Running in Perplexity-only mode")

    # Initialize thread-safe components
    rate_limiter = RateLimiter()
    max_history = config.get("MAX_HISTORY_PER_USER", 50)
    cleanup_interval = config.get("USER_LOCK_CLEANUP_INTERVAL", 3600)
    conversation_manager = ThreadSafeConversationManager(
        max_history_per_user=max_history, cleanup_interval=cleanup_interval
    )

    logger.info("All bot dependencies initialized successfully")

    # Run startup health checks
    try:
        logger.info("Running API health checks...")
        # Health checks will be initiated after bot is ready (in on_ready event)
        logger.info("Health checks will be initiated after bot startup")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to setup health monitoring: {e}")

    # Return dependency injection container
    return {
        "logger": logger,
        "bot": bot,
        "client": client,
        "perplexity_client": perplexity_client,
        "rate_limiter": rate_limiter,
        "conversation_manager": conversation_manager,
        "config": config,  # Pass full config for orchestrator settings
        "ALLOWED_CHANNELS": config["ALLOWED_CHANNELS"],
        "BOT_PRESENCE": config["BOT_PRESENCE"],
        "ACTIVITY_TYPE": config["ACTIVITY_TYPE"],
        "ACTIVITY_STATUS": config["ACTIVITY_STATUS"],
        "DISCORD_TOKEN": config["DISCORD_TOKEN"],
        "RATE_LIMIT": config["RATE_LIMIT"],
        "RATE_LIMIT_PER": config["RATE_LIMIT_PER"],
        "GPT_MODEL": config["GPT_MODEL"],
        "SYSTEM_MESSAGE": config["SYSTEM_MESSAGE"],
        "OUTPUT_TOKENS": config["OUTPUT_TOKENS"],
    }


async def _process_message_core(
    message: discord.Message, deps: dict[str, Any], is_dm: bool = True
) -> None:
    """Core message processing logic shared by DM and channel message handlers.

    This function contains the common message processing workflow to eliminate
    code duplication between DM and channel message processing.

    Args:
        message (discord.Message): The Discord message object to process
        deps (Dict[str, Any]): Dependency injection container with all bot components
        is_dm (bool): True for DMs, False for channel messages (affects logging/error messages)

    Returns:
        None: Function handles all response logic internally

    Side Effects:
        - Updates user's conversation history via thread-safe manager
        - Sends response message(s) to Discord
        - Logs all relevant events and errors
        - Applies rate limiting
    """
    logger = deps["logger"]
    rate_limiter = deps["rate_limiter"]
    conversation_manager = deps["conversation_manager"]

    # Prepare context-specific strings for logging and error messages
    if is_dm:
        context = f"DM from {message.author.name} (ID: {message.author.id})"
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
        context = (
            f"channel message in #{message.channel.name} from "
            f"{message.author.name} (ID: {message.author.id})"
        )
        rate_limit_msg = "⏱️ Rate limit exceeded! Please wait a moment before mentioning me again."
        error_msg = MessageFormatter.error_message(
            message.author.mention,
            "🔧 Sorry, I encountered an error while processing your message. "
            "Please try again in a moment.",
        )
        display_content = clean_message_content(clean_content, 100)

    try:
        logger.info(f"Processing {context}: {display_content}...")

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
                logger.error(f"Failed to send rate limit message to {context}")
            logger.warning(f"Rate limit exceeded for {context}")
            return

        # Get conversation summary using consolidated thread-safe manager
        conversation_summary = conversation_manager.get_conversation_summary_formatted(
            message.author.id
        )

        # Generate AI response using smart orchestrator
        response, suppress_embeds, embed_data = await get_smart_response(
            message.content,
            message.author,
            conversation_summary,
            conversation_manager,  # Pass manager instead of dict
            logger,
            deps["client"],
            deps["perplexity_client"],
            deps["GPT_MODEL"],
            deps["SYSTEM_MESSAGE"],
            deps["OUTPUT_TOKENS"],
            deps["config"],  # Pass config for orchestrator settings
        )

        # Send response with automatic message splitting if needed
        logger.debug(f"About to send response to Discord: {response[:200]}...")
        logger.debug(f"Response length: {len(response)} characters")
        await send_formatted_message(
            message.channel, response, deps, suppress_embeds=suppress_embeds, embed_data=embed_data
        )
        logger.info(f"Successfully processed and responded to {context}")

    except Exception as e:
        logger.exception("Error processing %s", context)

        # Classify error for better user messaging
        error_details = classify_error(e)
        user_friendly_msg = (
            error_details.user_message if hasattr(error_details, "user_message") else error_msg
        )

        if not await safe_discord_send(message.channel, user_friendly_msg, logger):
            logger.exception("Failed to send error message for %s", context)


async def process_dm_message(message: discord.Message, deps: dict[str, Any]) -> None:
    """Process direct messages with comprehensive error handling and thread-safe operations.

    Delegates to the core message processing logic with DM-specific context.

    Args:
        message (discord.Message): The Discord message object to process
        deps (Dict[str, Any]): Dependency injection container with all bot components
    """
    await _process_message_core(message, deps, is_dm=True)


async def process_channel_message(message: discord.Message, deps: dict[str, Any]) -> None:
    """Process channel messages with comprehensive error handling and thread-safe operations.

    Delegates to the core message processing logic with channel-specific context.

    Args:
        message (discord.Message): The Discord message object to process
        deps (Dict[str, Any]): Dependency injection container with all bot components
    """
    await _process_message_core(message, deps, is_dm=False)


def find_split_index(message: str, middle_index: int) -> int:
    """Find optimal split point for long messages, preferring line breaks.

    Attempts to split at natural boundaries (newlines) near the middle to
    maintain readability when breaking up long messages.

    Args:
        message (str): The message to find a split point in
        middle_index (int): The preferred middle position to split around

    Returns:
        int: Index position to split the message at
    """
    # Try to find a newline before the middle point for cleaner splitting
    split_index = message.rfind("\n", 0, middle_index)
    if split_index == -1:
        # No newline found, split at middle
        split_index = middle_index
    return split_index


def adjust_for_code_block(message: str, before_split: str, middle_index: int) -> tuple[str, str]:
    """Adjust message splitting to preserve code block integrity.

    Ensures that code blocks (marked with ```) are not split in the middle,
    which would break Discord's markdown formatting.

    Args:
        message (str): The full message being split
        before_split (str): The portion before the split point
        middle_index (int): The original middle split position

    Returns:
        Tuple[str, str]: (adjusted_before_split, adjusted_after_split)
    """
    # Count code block markers to detect if we're inside a code block
    if before_split.count("```") % 2 != 0:
        # We're inside a code block, need to find the end
        split_index = message.find("\n", middle_index)
        if split_index == -1:
            split_index = middle_index
        before_split = message[:split_index]
        after_split = message[split_index:]
        return before_split, after_split
    # Not in a code block, use original split
    after_split = message[len(before_split) :]
    return before_split, after_split


async def send_formatted_message(
    channel: discord.TextChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    embed_data: dict | None = None,
) -> None:
    """Send a formatted message to Discord, handling both embeds and message splitting.

    This function determines whether to send an embed or plain text message,
    and handles message splitting for long content while preserving embed functionality.

    Args:
        channel: Discord channel to send message to
        message: Message content to send
        deps: Dependency container for logging
        suppress_embeds: Whether to suppress link embeds (for plain text messages)
        embed_data: Optional embed data from Perplexity processing
    """
    logger = deps["logger"]

    # If we have embed data (from Perplexity web search), use embed for longer content
    if embed_data and "embed" in embed_data:
        embed = embed_data["embed"]
        clean_text = embed_data.get("clean_text", message)

        # Check if the original content was truncated in the embed
        embed_description = embed.description or ""
        was_truncated = len(clean_text) > 4096 and embed_description.endswith("...")

        if was_truncated:
            # Content was truncated - need to split and send remaining parts
            citations = embed_data.get("citations", {})
            logger.debug(
                f"Embed content was truncated ({len(clean_text)} chars), splitting message"
            )
            await send_split_message_with_embed(channel, clean_text, deps, embed, citations)
            return
        # Content fits in embed - send normally
        try:
            logger.debug(f"Sending message with citation embed ({len(message)} chars)")
            await channel.send(message, embed=embed)
            logger.debug("Successfully sent message with embed")
            return  # Successfully sent embed - exit function  # noqa: TRY300
        except discord.HTTPException:
            logger.exception("Failed to send embed message")
            logger.warning("Falling back to split message without embed")
                # Continue to fallback logic below

    # No embed data OR embed send failed - use regular message splitting (2000 char limit)
    if len(message) <= 2000:
        # Message fits in single regular message
        try:
            logger.debug(f"Sending regular message ({len(message)} chars)")
            await channel.send(message, suppress_embeds=suppress_embeds)
            logger.debug(f"Sent message ({len(message)} chars)")
        except discord.HTTPException:
            logger.exception("Discord API error sending message")
            raise
        else:
            return
    else:
        # Message too long for regular message - need to split
        await send_split_message(channel, message, deps, suppress_embeds)


async def send_split_message_with_embed(
    channel: discord.TextChannel,
    message: str,
    deps: dict[str, Any],
    embed: discord.Embed,
    citations: dict[str, str] | None = None,
) -> None:
    """Send a long message with citation embeds, maintaining citations across parts."""
    logger = deps["logger"]

    # Find optimal split point for 4096 char limit (embed description)
    # We want the first part to fit in the embed description
    if len(message) > 4090:  # Leave room for "..."
        split_index = find_optimal_split_point(message, 4090)
        _, after_split = adjust_split_for_code_blocks(message, split_index)
    else:
        after_split = ""

    # Clean up the splits
    message_part2 = after_split.strip()

    # Send first part with the provided embed (already contains formatted citations)
    try:
        await channel.send("", embed=embed)  # Empty message text, content is in embed
        logger.debug(
            f"Sent message part 1 with embed ({len(embed.description or '')} chars in embed)"
        )
    except discord.HTTPException:
        logger.exception("Discord API error sending message part 1 with embed")
        raise

        # Send remaining parts - if they contain citations, format as embeds too
    if message_part2 and citations:
        # Check if remaining content has citations
        remaining_citations = {
            cite_num: url
            for cite_num, url in citations.items()
            if f"[{cite_num}]" in message_part2
        }

        if remaining_citations:
            # Create embed for remaining content with citations
            logger.debug(f"Creating continuation embed with {len(remaining_citations)} citations")
            continuation_embed = citation_embed_formatter.create_citation_embed(
                message_part2, remaining_citations, footer_text="🌐 Web search results (continued)"
            )

            # Check if this part also needs splitting
            if len(message_part2) > 4096:
                await send_split_message_with_embed(
                    channel, message_part2, deps, continuation_embed, remaining_citations
                )
            else:
                try:
                    await channel.send("", embed=continuation_embed)
                    logger.debug(f"Sent continuation embed ({len(message_part2)} chars)")
                except discord.HTTPException:
                    logger.exception(
                        "Failed to send continuation embed, falling back to plain text"
                    )
                    await send_split_message(channel, message_part2, deps, suppress_embeds=False)
        else:
            # No citations in remaining part - send as plain text
            await send_split_message(channel, message_part2, deps, suppress_embeds=False)
    elif message_part2:
        # No citations available - send remaining as plain text
        await send_split_message(channel, message_part2, deps, suppress_embeds=False)


async def send_split_message(
    channel: discord.TextChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    _recursion_depth: int = 0,
) -> None:
    """Send messages with automatic splitting for Discord's 2000 character limit.

    Handles long messages by intelligently splitting them at natural boundaries
    while preserving code blocks and other formatting. Includes safeguards
    against infinite recursion.

    Args:
        channel (discord.TextChannel): Discord channel to send message to
        message (str): Message content to send (may exceed 2000 chars)
        deps (Dict[str, Any]): Dependency container for logging
        suppress_embeds (bool): Whether to suppress link embeds
        _recursion_depth (int): Internal recursion counter for safety

    Returns:
        None: Sends message(s) directly to Discord

    Raises:
        RecursionError: If recursion depth exceeds safety limit
        discord.HTTPException: If Discord API calls fail
    """
    # Recursion safety check
    max_recursion_depth = 10
    if _recursion_depth > max_recursion_depth:
        deps["logger"].error(
            f"Message splitting exceeded maximum recursion depth ({max_recursion_depth}). "
            f"Message length: {len(message)}. Truncating message."
        )
        # Send truncated message as fallback
        truncated = message[:1950] + "\n\n[Message truncated due to complexity]"
        await channel.send(truncated, suppress_embeds=suppress_embeds)
        return

    # If message fits in one Discord message, send it directly
    if len(message) <= 2000:
        try:
            deps["logger"].debug(f"Discord API call - message content: {message[:200]}...")
            deps["logger"].debug(f"Discord API call - suppress_embeds: {suppress_embeds}")
            await channel.send(message, suppress_embeds=suppress_embeds)
            if _recursion_depth == 0:  # Only log for top-level calls
                deps["logger"].debug(f"Sent message ({len(message)} chars)")
        except discord.HTTPException as e:
            deps["logger"].error(f"Discord API error sending message: {e}")
            raise
        return

    # Message needs splitting
    deps["logger"].debug(
        f"Splitting long message ({len(message)} chars) at recursion depth {_recursion_depth}"
    )

    middle_index = len(message) // 2
    split_index = find_optimal_split_point(message, middle_index)
    before_split, after_split = adjust_split_for_code_blocks(message, split_index)

    # Clean up the splits
    message_part1 = before_split.strip()
    message_part2 = after_split.strip()

    # Send first part (with embed suppression if needed)
    try:
        await channel.send(message_part1, suppress_embeds=suppress_embeds)
        deps["logger"].debug(f"Sent message part 1 ({len(message_part1)} chars)")
    except discord.HTTPException as e:
        deps["logger"].error(f"Discord API error sending message part 1: {e}")
        raise

    # Recursively send second part (without embed suppression to avoid affecting both parts)
    if message_part2:
        await send_split_message(
            channel,
            message_part2,
            deps,
            suppress_embeds=False,
            _recursion_depth=_recursion_depth + 1,
        )


async def _handle_incoming_message(
    message: discord.Message, deps: dict[str, Any], bot: discord.Client
) -> None:
    """Handle incoming message with comprehensive routing and error handling.

    Args:
        message: The Discord message to process
        deps: Dependency injection container
        bot: The Discord bot client
    """
    logger = deps["logger"]

    try:
        # Ignore messages from the bot itself
        if message.author == bot.user:
            return

        # Handle direct messages
        if isinstance(message.channel, discord.DMChannel):
            await process_dm_message(message, deps)
            return

        # Handle channel messages where bot is mentioned
        if isinstance(message.channel, discord.TextChannel):
            channel_name = message.channel.name
            is_allowed_channel = channel_name in deps["ALLOWED_CHANNELS"]
            is_mentioned = bot.user in message.mentions

            logger.debug(
                f"Channel message in #{channel_name} from {message.author.name}: "
                f"allowed={is_allowed_channel}, mentioned={is_mentioned}, "
                f"allowed_channels={deps['ALLOWED_CHANNELS']}"
            )

            if is_allowed_channel and is_mentioned:
                await process_channel_message(message, deps)
                return
            if is_allowed_channel and not is_mentioned:
                logger.debug(f"Message in allowed channel #{channel_name} but bot not mentioned")
            elif not is_allowed_channel:
                logger.debug(
                    f"Channel #{channel_name} not in allowed channels: "
                    f"{deps['ALLOWED_CHANNELS']}"
                )

        # Log ignored messages at debug level
        logger.debug(
            f"Ignored message from {message.author.name} in #{message.channel.name} "
            f"(not mentioned or allowed)"
        )

    except Exception:
        logger.exception(
            "Unhandled error in message processing for message from %s",
            message.author.name,
        )
        # Attempt to send error message if possible
        try:
            if isinstance(message.channel, discord.DMChannel | discord.TextChannel):
                await message.channel.send(
                    "🔧 An unexpected error occurred. The issue has been logged "
                    "for investigation."
                )
        except Exception:
            # If even the error message fails, just log it
            logger.exception("Failed to send error notification to user")


def register_event_handlers(bot: discord.Client, deps: dict[str, Any]) -> None:
    """Register all Discord event handlers with comprehensive error handling.

    Sets up event handlers for bot lifecycle events and message processing
    with proper logging and error recovery.

    Args:
        bot (discord.Client): The Discord client to register events on
        deps (Dict[str, Any]): Dependency container with all bot components

    Returns:
        None: Registers event handlers as side effects
    """
    logger = deps["logger"]

    @bot.event
    async def on_ready():
        """Handle bot ready event with full initialization."""
        try:
            logger.info(f"Bot logged in successfully as {bot.user.name} (ID: {bot.user.id})")
            logger.info(f"Connected to {len(bot.guilds)} Discord servers")
            logger.info(f"Configured bot presence: {deps['BOT_PRESENCE']}")
            logger.info(
                f"Configured activity: {deps['ACTIVITY_TYPE']} - {deps['ACTIVITY_STATUS']}"
            )
            logger.info(f"Allowed channels: {deps['ALLOWED_CHANNELS']}")
            logger.info(f"Bot will respond in channels: {deps['ALLOWED_CHANNELS']}")
            logger.info("Note: Bot must be mentioned (@botname) in allowed channels to respond")

            # Set bot presence and activity
            activity = set_activity_status(deps["ACTIVITY_TYPE"], deps["ACTIVITY_STATUS"])
            await bot.change_presence(
                activity=activity, status=discord.Status(deps["BOT_PRESENCE"])
            )

            # Now that the event loop is running, initiate health checks
            try:
                # Create and schedule health checks
                health_monitor = APIHealthMonitor()
                clients_for_health_check = {
                    "openai": deps.get("client"),
                    "perplexity": deps.get("perplexity_client"),
                }
                deps["_health_task"] = asyncio.create_task(
                    health_monitor.run_all_health_checks(clients_for_health_check, deps)
                )
                logger.info("Health monitoring initiated successfully")
            except Exception:
                logger.exception("Failed to initiate health checks")

            logger.info("Bot initialization completed successfully - ready to process messages")

        except Exception:
            logger.exception("Error in on_ready event")

    @bot.event
    async def on_disconnect():
        """Handle bot disconnect event."""
        logger.warning("Bot has disconnected from Discord")

    @bot.event
    async def on_resumed():
        """Handle bot resume event."""
        logger.info("Bot connection resumed successfully")

    @bot.event
    async def on_shard_ready(shard_id: int):
        """Handle shard ready event for scaled deployments."""
        logger.info(f"Shard {shard_id} is ready and connected")

    @bot.event
    async def on_message(message: discord.Message):
        """Handle all incoming messages with comprehensive routing and error handling.

        Routes messages to appropriate handlers based on channel type and mentions,
        with full error recovery and logging.
        """
        await _handle_incoming_message(message, deps, bot)


def run_bot(config: dict[str, Any]) -> None:
    """Initialize and run the Discord bot with comprehensive error handling.

    This is the main entry point for the bot. It initializes all components,
    registers event handlers, and starts the Discord connection.

    Args:
        config (Dict[str, Any]): Complete bot configuration dictionary

    Returns:
        None: Runs indefinitely until stopped

    Raises:
        ValueError: If configuration is invalid
        Exception: If bot initialization or startup fails
    """
    try:
        # Initialize all bot components
        deps = initialize_bot_and_dependencies(config)
        logger = deps["logger"]

        logger.info("Starting Discord bot...")

        # Register all event handlers
        register_event_handlers(deps["bot"], deps)

        # Start the bot (this blocks until the bot stops)
        logger.info("Connecting to Discord...")
        deps["bot"].run(deps["DISCORD_TOKEN"])

    except Exception as e:
        # Log critical startup errors
        if "logger" in locals():
            logger.critical(f"Fatal error starting bot: {e}", exc_info=True)
        else:
            # Fallback logging if logger not initialized
            pass
        raise
