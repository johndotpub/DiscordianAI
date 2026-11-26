"""Discord bot startup wiring.

This module holds ``initialize_bot_and_dependencies`` (builds the Discord
client, provider clients, router, and shared services) and ``run_bot`` (starts
the manager). Event handlers and graceful shutdown live in ``bot_manager.py``,
mention and DM routing live in ``message_router.py``, and message splitting and
delivery live in ``message_splitter.py``.

The bot uses a ``BotDependencies`` dataclass for typed dependency injection,
replacing the previous untyped ``deps`` dict pattern.
"""

import logging
from typing import Any

import discord

from .bot_manager import DiscordBotManager
from .config import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_CONVERSATION_TTL_SECONDS,
    DEFAULT_INPUT_TOKENS,
    DEFAULT_MAX_HISTORY_PER_USER,
    DEFAULT_PERPLEXITY_MODEL,
    DEFAULT_REASONING_EFFORT,
)
from .connection_pool import get_connection_pool_manager
from .conversation_manager import ThreadSafeConversationManager
from .dependencies import BotDependencies
from .error_handling import get_circuit_breaker
from .health_server import HealthServer
from .providers.registry import build_configured_clients
from .rate_limits import RateLimiter
from .routing import build_router


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

    # Configure Discord intents for optimal performance
    intents = discord.Intents.default()
    intents.typing = False
    intents.presences = False

    # Initialize connection pool manager for optimized API clients
    pool_manager = get_connection_pool_manager(config)
    router = build_router(config)
    logger.info("Routing configured with %s", router.router_id)

    configured_clients = build_configured_clients(pool_manager, config, logger)
    client = configured_clients.get("openai")
    perplexity_client = configured_clients.get("perplexity")

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
            "Running in hybrid mode (OpenAI + Perplexity); smart orchestration enabled",
        )
    elif client:
        logger.info("Running in OpenAI-only mode")
    elif perplexity_client:
        logger.info("Running in Perplexity-only mode")

    # Initialize thread-safe components
    max_history = config.get("MAX_HISTORY_PER_USER", DEFAULT_MAX_HISTORY_PER_USER)
    conversation_ttl = config.get(
        "CONVERSATION_TTL_SECONDS",
        DEFAULT_CONVERSATION_TTL_SECONDS,
    )
    cleanup_interval = config.get("USER_LOCK_CLEANUP_INTERVAL", 3600)
    logger.info("Health checks will run after bot startup")

    circuit_breakers = {
        provider: get_circuit_breaker(provider) for provider in ("openai", "perplexity")
    }

    deps = BotDependencies(
        bot=discord.Client(intents=intents),
        logger=logger,
        config=config,
        client=client,
        perplexity_client=perplexity_client,
        connection_pool_manager=pool_manager,
        router=router,
        circuit_breakers=circuit_breakers,
        allowed_channels=config["ALLOWED_CHANNELS"],
        allowed_channel_ids=config.get("ALLOWED_CHANNEL_IDS", []),
        allowed_guilds=config.get("ALLOWED_GUILDS", []),
        allowed_guild_ids=config.get("ALLOWED_GUILD_IDS", []),
        bot_presence=config["BOT_PRESENCE"],
        activity_type=config["ACTIVITY_TYPE"],
        activity_status=config["ACTIVITY_STATUS"],
        discord_token=config["DISCORD_TOKEN"],
        rate_limit=config["RATE_LIMIT"],
        rate_limit_period=config["RATE_LIMIT_PER"],
        gpt_model=config["GPT_MODEL"],
        reasoning_effort=config.get("REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
        web_tools=config.get("WEB_TOOLS", True),
        perplexity_model=config.get("PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL),
        system_message=config["SYSTEM_MESSAGE"],
        output_tokens=config["OUTPUT_TOKENS"],
        perplexity_output_tokens=config.get("PERPLEXITY_OUTPUT_TOKENS", config["OUTPUT_TOKENS"]),
        input_tokens=config.get("INPUT_TOKENS", DEFAULT_INPUT_TOKENS),
        context_window=config.get("CONTEXT_WINDOW", DEFAULT_CONTEXT_WINDOW),
        rate_limiter=RateLimiter(),
        conversation_manager=ThreadSafeConversationManager(
            max_history_per_user=max_history,
            cleanup_interval=cleanup_interval,
            conversation_ttl_seconds=conversation_ttl,
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
    """Initialize and run the Discord bot using DiscordBotManager.

    A fatal startup or run-loop error propagates to the caller. The command-line
    entry point logs it once, with a traceback, before exiting.
    """
    deps = initialize_bot_and_dependencies(config)
    deps.logger.info("Starting Discord bot manager")
    manager = DiscordBotManager(deps)
    manager.run()
