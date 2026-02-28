"""Discord bot core module with event handling and message processing.

This module provides the main Discord bot implementation including:
- Bot initialization and dependency injection
- Event handlers for Discord messages
- Message splitting for long responses
- Graceful shutdown with signal handlers
- Integration with AI services (OpenAI, Perplexity)

The bot uses a dependency injection pattern via a `deps` dictionary
to provide loose coupling and testability.
"""

# Standard library imports
import logging
from typing import Any

# Third-party imports
import discord

from .bot_manager import DiscordBotManager
from .connection_pool import get_connection_pool_manager
from .conversation_manager import ThreadSafeConversationManager
from .rate_limits import RateLimiter


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
    intents.typing = False
    intents.presences = False

    # Initialize connection pool manager for optimized API clients
    pool_manager = get_connection_pool_manager(config)

    # Initialize OpenAI client if API key is provided
    client = None
    if config["OPENAI_API_KEY"]:
        try:
            client = pool_manager.create_openai_client(
                api_key=config["OPENAI_API_KEY"],
                base_url=config["OPENAI_API_URL"],
            )
            logger.info(
                "OpenAI client initialized with model: %s (connection pooling enabled)",
                config["GPT_MODEL"],
            )
        except Exception as e:
            logger.exception("Failed to initialize OpenAI client")
            error_msg = "OpenAI client initialization failed"
            raise RuntimeError(error_msg) from e
    else:
        logger.info("No OpenAI API key provided - GPT models disabled")

    # Initialize Perplexity client for web search if API key is provided
    perplexity_client = None
    if config["PERPLEXITY_API_KEY"]:
        try:
            perplexity_client = pool_manager.create_perplexity_client(
                api_key=config["PERPLEXITY_API_KEY"],
                base_url=config["PERPLEXITY_API_URL"],
            )
            logger.info(
                "Perplexity client initialized successfully for web search "
                "(connection pooling enabled)",
            )
        except Exception as e:
            logger.exception("Failed to initialize Perplexity client")
            error_msg = "Perplexity client initialization failed"
            raise RuntimeError(error_msg) from e
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
            "Running in HYBRID mode (OpenAI + Perplexity) - Smart AI orchestration enabled",
        )
    elif client:
        logger.info("Running in OpenAI-only mode")
    elif perplexity_client:
        logger.info("Running in Perplexity-only mode")

    # Initialize thread-safe components
    max_history = config.get("MAX_HISTORY_PER_USER", 50)
    cleanup_interval = config.get("USER_LOCK_CLEANUP_INTERVAL", 3600)
    logger.info("Health checks will be initiated after bot startup")

    # Return dependency injection container
    deps = {
        "logger": logger,
        "bot": discord.Client(intents=intents),
        "client": client,
        "perplexity_client": perplexity_client,
        "config": config,
        "connection_pool_manager": pool_manager,
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

    # Add thread-safe components to deps
    deps["rate_limiter"] = RateLimiter()
    deps["conversation_manager"] = ThreadSafeConversationManager(
        max_history_per_user=max_history,
        cleanup_interval=cleanup_interval,
    )

    return deps


# Message processing is now handled by src/message_processor.py
# Message splitting and formatting are now handled by src/message_splitter.py


def run_bot(config: dict[str, Any]) -> None:
    """Initialize and run the Discord bot using DiscordBotManager."""
    try:
        deps = initialize_bot_and_dependencies(config)
        bot_logger = deps["logger"]
        bot_logger.info("Starting Discord bot manager...")
        manager = DiscordBotManager(deps)
        manager.run()
    except Exception as e:
        # Fatal startup error
        if "deps" in locals() and "logger" in deps:
            deps["logger"].critical("Fatal error starting bot: %s", e, exc_info=True)
        else:
            print(f"CRITICAL: Fatal error starting bot: {e}")  # noqa: T201
        raise
