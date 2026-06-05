"""Discord bot core module with event handling and message processing.

This module provides the main Discord bot implementation including:
- Bot initialization and dependency injection
- Event handlers for Discord messages
- Message splitting for long responses
- Graceful shutdown with signal handlers
- Integration with AI services (OpenAI, Perplexity)

The bot uses a ``BotDependencies`` dataclass for typed dependency injection,
replacing the previous untyped ``deps`` dict pattern.
"""

import logging
from typing import Any

import discord

from .bot_manager import DiscordBotManager
from .connection_pool import get_connection_pool_manager
from .conversation_manager import ThreadSafeConversationManager
from .dependencies import BotDependencies
from .health_server import HealthServer
from .rate_limits import RateLimiter


def initialize_bot_and_dependencies(config: dict[str, Any]) -> BotDependencies:
    """Initialize Discord bot and all required dependencies with comprehensive error handling.

    This function sets up the Discord client, API clients (OpenAI and Perplexity),
    logging, rate limiting, and conversation management in a production-ready manner.

    Args:
        config: Configuration dictionary containing all bot settings
            including API keys, Discord settings, and operational parameters.

    Returns:
        BotDependencies: Typed dependency container with all initialized components.

    Raises:
        ValueError: If critical configuration is missing or invalid
        RuntimeError: If client initialization fails
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

    deps = BotDependencies(
        bot=discord.Client(intents=intents),
        logger=logger,
        config=config,
        client=client,
        perplexity_client=perplexity_client,
        connection_pool_manager=pool_manager,
        allowed_channels=config["ALLOWED_CHANNELS"],
        bot_presence=config["BOT_PRESENCE"],
        activity_type=config["ACTIVITY_TYPE"],
        activity_status=config["ACTIVITY_STATUS"],
        discord_token=config["DISCORD_TOKEN"],
        rate_limit=config["RATE_LIMIT"],
        rate_limit_period=config["RATE_LIMIT_PER"],
        gpt_model=config["GPT_MODEL"],
        perplexity_model=config.get("PERPLEXITY_MODEL", "sonar-pro"),
        system_message=config["SYSTEM_MESSAGE"],
        output_tokens=config["OUTPUT_TOKENS"],
        rate_limiter=RateLimiter(),
        conversation_manager=ThreadSafeConversationManager(
            max_history_per_user=max_history,
            cleanup_interval=cleanup_interval,
        ),
    )

    # Initialize health server
    health_server = HealthServer(
        deps.to_dict(),
        host=config.get("HEALTH_HOST", "127.0.0.1"),
        port=config.get("HEALTH_PORT", 8080),
    )
    deps.health_server = health_server

    return deps


def run_bot(config: dict[str, Any]) -> None:
    """Initialize and run the Discord bot using DiscordBotManager."""
    deps: BotDependencies | None = None
    try:
        deps = initialize_bot_and_dependencies(config)
        deps.logger.info("Starting Discord bot manager...")
        manager = DiscordBotManager(deps)
        manager.run()
    except Exception as e:
        # Fatal startup error
        if isinstance(deps, BotDependencies):
            deps.logger.critical("Fatal error starting bot: %s", e, exc_info=True)
        else:
            print(f"CRITICAL: Fatal error starting bot: {e}")  # noqa: T201
        raise
