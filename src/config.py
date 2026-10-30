"""Configuration management and constants for DiscordianAI.

This module serves as the single source of truth for all configuration:
- API constants (models, URLs, patterns)
- Discord settings (limits, activity types)
- Performance tuning (cache TTL, connection pools)
- Smart routing patterns for AI service selection
- Configuration loading from files and environment variables

Configuration hierarchy (highest priority first):
1. Environment variables
2. Config file (config.ini)
3. Default values
"""

import argparse
import configparser
import logging
import os
from pathlib import Path
import re
from typing import Any

# ============================================================================
# CENTRALIZED CONFIGURATION CONSTANTS
# ============================================================================

# ============================================================================
# API CONFIGURATION
# ============================================================================

# OpenAI Models
OPENAI_MODEL_PREFIX = "gpt-6"
DEFAULT_OPENAI_MODEL = "gpt-6-luna"

# Canonical model identifiers that we document. The GPT-6 generation is current;
# the GPT-5 entries remain selectable until the provider retires them on 2026-12-11.
OPENAI_VALID_MODELS = [
    DEFAULT_OPENAI_MODEL,  # Current generation - cost-effective default
    "gpt-6.1-sol",  # Current generation - GPT-6.1
    "gpt-6.1-terra",  # Current generation - GPT-6.1
    "gpt-6-astra",  # Current generation - GPT-6
    "gpt-6-sol",  # Current generation - GPT-6
    # Legacy GPT-5 models: selectable only until the 2026-12-11 shutdown.
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
]

# Supported families accept point releases and dated snapshots within the family.
OPENAI_MODEL_FAMILIES = (
    OPENAI_MODEL_PREFIX,
    "gpt-6.1",
    "gpt-5.6",
    "gpt-5",
)

# Models the provider has already retired; rejected even though the family matches.
OPENAI_RETIRED_MODELS = ("gpt-5-chat",)


# Perplexity Agent API model catalogue. The legacy Sonar names still answer on
# Chat Completions, but they are not part of the current catalogue and this bot
# no longer calls that interface.
DEFAULT_PERPLEXITY_MODEL = "perplexity/sonar"
PERPLEXITY_MODELS = [
    DEFAULT_PERPLEXITY_MODEL,
]


def _matches_model_family(model: str, family: str) -> bool:
    """Return True when ``model`` is ``family`` or extends it at a boundary."""
    return model == family or model.startswith((f"{family}-", f"{family}."))


def is_supported_openai_model(model: str | None) -> bool:
    """Return True if the model belongs to a supported OpenAI GPT family.

    A model is accepted when it is one of the documented ``OPENAI_VALID_MODELS``
    or when it extends a family from ``OPENAI_MODEL_FAMILIES`` at a hyphen, a
    dot, or the end of the identifier. That covers point releases and dated
    snapshots such as ``gpt-6-luna-2026-09-01`` while rejecting a different
    family (``gpt-7``), a malformed prefix (``gpt6-luna``), and identifiers the
    provider has already retired (``gpt-5-chat``).
    """
    if not model:
        return False

    if any(_matches_model_family(model, retired) for retired in OPENAI_RETIRED_MODELS):
        return False

    if model in OPENAI_VALID_MODELS:
        return True

    return any(_matches_model_family(model, family) for family in OPENAI_MODEL_FAMILIES)


# API URL Patterns for validation (stricter patterns with end anchor)
VALID_OPENAI_URL_PATTERN = re.compile(r"https://api\.openai\.com/v\d+/?$")
VALID_PERPLEXITY_URL_PATTERN = re.compile(r"https://api\.perplexity\.ai/?$")

# Default API URLs
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/"
DEFAULT_PERPLEXITY_API_URL = "https://api.perplexity.ai"

# ============================================================================
# DISCORD CONFIGURATION
# ============================================================================

# Discord Activity Types
DISCORD_ACTIVITY_TYPES = ["playing", "streaming", "listening", "watching", "custom", "competing"]
DEFAULT_ACTIVITY_TYPE = "listening"
DEFAULT_BOT_PRESENCE = "online"
DEFAULT_ACTIVITY_STATUS = "Humans"

# Discord Message Constants
MESSAGE_LIMIT = 2000  # Discord's hard limit for regular messages
MESSAGE_BUFFER = 100
EMBED_LIMIT = 4096  # Discord's hard limit for embed descriptions
EMBED_SAFE_LIMIT = 3840  # Safe margin for citation expansion and formatting
MAX_SPLIT_CHUNKS = 50  # Safety cap for one message's split delivery

# ============================================================================
# PERFORMANCE & CACHING
# ============================================================================

# Cache Configuration
DEFAULT_CACHE_TTL = 300.0  # 5 minutes

# Rate Limiting
DEFAULT_RATE_LIMIT = 10
DEFAULT_RATE_LIMIT_PER = 60  # seconds

# Connection Pooling
DEFAULT_OPENAI_MAX_CONNECTIONS = 50
DEFAULT_OPENAI_MAX_KEEPALIVE = 10
DEFAULT_PERPLEXITY_MAX_CONNECTIONS = 30
DEFAULT_PERPLEXITY_MAX_KEEPALIVE = 5

# ============================================================================
# AI ORCHESTRATOR CONFIGURATION
# ============================================================================

# Conversation Management
DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY = 6
DEFAULT_MAX_HISTORY_PER_USER = 50
DEFAULT_CONVERSATION_TTL_SECONDS = 1800  # 30 minutes
DEFAULT_USER_LOCK_CLEANUP_INTERVAL = 3600  # 1 hour

# Routing
DEFAULT_ROUTER_MODE = "heuristic"
DEFAULT_ROUTER_WEB_THRESHOLD_CHANNEL = 0.10
DEFAULT_ROUTER_WEB_THRESHOLD_ANNOUNCE = 0.07
DEFAULT_ROUTER_WEB_THRESHOLD_DM = 0.20

# Token and Context Limits
DEFAULT_INPUT_TOKENS = 120000
DEFAULT_OUTPUT_TOKENS = 8000
DEFAULT_PERPLEXITY_OUTPUT_TOKENS = DEFAULT_OUTPUT_TOKENS
DEFAULT_CONTEXT_WINDOW = 128000

# Web scraping budgets
DEFAULT_MAX_URLS_PER_MESSAGE = 3
DEFAULT_MAX_TOTAL_SCRAPED_CHARS = 60000
DEFAULT_SCRAPE_DEADLINE_SECONDS = 20.0

# ============================================================================
# VALIDATION THRESHOLDS
# ============================================================================

MAX_OUTPUT_TOKENS_CEILING = DEFAULT_CONTEXT_WINDOW
MAX_OUTPUT_TOKENS_THRESHOLD = MAX_OUTPUT_TOKENS_CEILING
MAX_OUTPUT_TOKENS_COST_WARNING = 50000
MIN_OPENAI_OUTPUT_TOKENS_WARNING = 512
MAX_INPUT_TOKENS_THRESHOLD = 200000
MAX_RATE_LIMIT_THRESHOLD = 100
MAX_RECOMMENDED_REQ_PER_MIN = 60
SECONDS_PER_MINUTE = 60

# ============================================================================
# MESSAGE PROCESSING PATTERNS
# ============================================================================

# Discord markup pattern for routing sanitization (routing-only; never applied to
# cache keys, API payloads, conversation history, or log output).
DISCORD_MARKUP_PATTERN = re.compile(
    r"<a?:\w+:\d+>"  # Custom / animated emojis
    r"|<@!?\d+>"  # User mentions
    r"|<@&\d+>"  # Role mentions
    r"|<#\d+>"  # Channel mentions
    r"|<t:\d+(?::[tTdDfFR])?>"  # Timestamps
)

# Citation pattern
CITATION_PATTERN = re.compile(r"\[(\d+)\]")

# URL and link detection used by delivery and Perplexity citation handling.
_BARE_URL_PATTERN_STR = (
    r"(?:https?://)?[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}"
    r"(?:/[^\s]*)?"
)

URL_PATTERN = re.compile(r"https?://[^\s\[\]()]+[^\s\[\]().,;!?]")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BARE_URL_PATTERN = re.compile(_BARE_URL_PATTERN_STR)

# ============================================================================
# ERROR MESSAGES
# ============================================================================

ERROR_MESSAGES = {
    "web_search_unavailable": (
        "🔍 Web search is temporarily unavailable. Please try again in a few moments."
    ),
    "ai_service_unavailable": (
        "🤖 AI service is temporarily unavailable. Please try again in a few moments."
    ),
    "no_response_generated": (
        "🔧 I'm having trouble generating a response. Please try rephrasing your question."
    ),
    "both_services_unavailable": (
        "🔧 All AI services are temporarily unavailable. Please try again later."
    ),
    "configuration_error": (
        "⚠️ AI services are not properly configured. Please contact the administrator."
    ),
    "unexpected_error": (
        "🔧 An unexpected error occurred while processing your request. Please try again."
    ),
    "rate_limit_exceeded": (
        "⏱️ Rate limit exceeded! Please wait a moment before sending another message."
    ),
    "api_error": (
        "🔧 There was an issue connecting to the AI service. Please try again in a moment."
    ),
    "message_too_long": ("📝 Your message is too long. Please break it into smaller parts."),
    "empty_message": "❓ Please send a message for me to respond to.",
}

# ============================================================================
# CONFIGURATION DEFAULTS
# ============================================================================

# Single table for values used both when a config file omits a key and when a
# value in the file cannot be parsed. Parser helpers and _apply_config_defaults
# both read from this mapping so each default is written only once.
_CONFIG_DEFAULTS: dict[str, Any] = {
    "DISCORD_TOKEN": None,
    "ALLOWED_CHANNELS": [],
    "ALLOWED_CHANNEL_IDS": [],
    "ALLOWED_GUILDS": [],
    "ALLOWED_GUILD_IDS": [],
    "BOT_PRESENCE": DEFAULT_BOT_PRESENCE,
    "ACTIVITY_TYPE": DEFAULT_ACTIVITY_TYPE,
    "ACTIVITY_STATUS": DEFAULT_ACTIVITY_STATUS,
    "OPENAI_API_KEY": None,
    "OPENAI_API_URL": DEFAULT_OPENAI_API_URL,
    "PERPLEXITY_API_KEY": None,
    "PERPLEXITY_API_URL": DEFAULT_PERPLEXITY_API_URL,
    "PERPLEXITY_MODEL": DEFAULT_PERPLEXITY_MODEL,
    "GPT_MODEL": DEFAULT_OPENAI_MODEL,
    "INPUT_TOKENS": DEFAULT_INPUT_TOKENS,
    "OUTPUT_TOKENS": DEFAULT_OUTPUT_TOKENS,
    "PERPLEXITY_OUTPUT_TOKENS": None,
    "CONTEXT_WINDOW": DEFAULT_CONTEXT_WINDOW,
    "SYSTEM_MESSAGE": "You are a helpful assistant.",
    "RATE_LIMIT": DEFAULT_RATE_LIMIT,
    "RATE_LIMIT_PER": DEFAULT_RATE_LIMIT_PER,
    "OPENAI_MAX_CONNECTIONS": DEFAULT_OPENAI_MAX_CONNECTIONS,
    "OPENAI_MAX_KEEPALIVE": DEFAULT_OPENAI_MAX_KEEPALIVE,
    "PERPLEXITY_MAX_CONNECTIONS": DEFAULT_PERPLEXITY_MAX_CONNECTIONS,
    "PERPLEXITY_MAX_KEEPALIVE": DEFAULT_PERPLEXITY_MAX_KEEPALIVE,
    "LOOKBACK_MESSAGES_FOR_CONSISTENCY": DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY,
    "MAX_HISTORY_PER_USER": DEFAULT_MAX_HISTORY_PER_USER,
    "CONVERSATION_TTL_SECONDS": DEFAULT_CONVERSATION_TTL_SECONDS,
    "USER_LOCK_CLEANUP_INTERVAL": DEFAULT_USER_LOCK_CLEANUP_INTERVAL,
    "ROUTER_MODE": DEFAULT_ROUTER_MODE,
    "ROUTER_WEB_THRESHOLD_CHANNEL": DEFAULT_ROUTER_WEB_THRESHOLD_CHANNEL,
    "ROUTER_WEB_THRESHOLD_ANNOUNCE": DEFAULT_ROUTER_WEB_THRESHOLD_ANNOUNCE,
    "ROUTER_WEB_THRESHOLD_DM": DEFAULT_ROUTER_WEB_THRESHOLD_DM,
    "ENTITY_DETECTION_MIN_WORDS": 10,
    "MAX_URLS_PER_MESSAGE": DEFAULT_MAX_URLS_PER_MESSAGE,
    "MAX_TOTAL_SCRAPED_CHARS": DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    "SCRAPE_DEADLINE_SECONDS": DEFAULT_SCRAPE_DEADLINE_SECONDS,
    "LOG_FILE": "bot.log",
    "LOG_LEVEL": "INFO",
    "DISCORDIANAI_LOG_COLOR": True,
    "HEALTH_ENABLED": True,
    "HEALTH_HOST": "127.0.0.1",
    "HEALTH_PORT": 8080,
    "HEALTH_PROVIDER_STALE_SECONDS": 300,
}

# ============================================================================
# CONFIGURATION FUNCTIONS
# ============================================================================


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="GPT-based Discord bot.")
    parser.add_argument("--conf", help="Configuration file path")
    parser.add_argument("--folder", help="Base folder for config and logs")
    return parser.parse_args()


def load_config(config_file: str | None = None, base_folder: str | None = None) -> dict[str, Any]:
    """Load configuration from a file (if provided), then environment variables.

    With a clear hierarchy.

    Args:
        config_file: Path to the configuration file. If None, only env vars and defaults are used.
        base_folder: Base folder to resolve relative paths like the config file and log file.

    Returns:
        dict: Configuration dictionary with all settings.
    """
    config = configparser.ConfigParser()
    config_data = {}

    # Get logger for error handling
    logger = logging.getLogger(__name__)

    # Provenance for provider selection. A blank key explicitly disables a
    # provider; otherwise, any provider-specific option means it was selected.
    openai_explicit = False
    perplexity_explicit = False
    openai_key_disabled = False
    perplexity_key_disabled = False

    # If base_folder is provided, resolve config_file and log file paths
    if base_folder and config_file and not Path(config_file).is_absolute():
        config_file = str(Path(base_folder) / config_file)

    if config_file and Path(config_file).exists():
        try:
            config.read(config_file)
            openai_explicit, openai_key_disabled = _provider_option_flags(config, "OPENAI")
            perplexity_explicit, perplexity_key_disabled = _provider_option_flags(
                config, "PERPLEXITY"
            )
            _parse_discord_config(config, config_data, logger)
            _parse_default_config(config, config_data, logger)
            _parse_scraping_config(config, config_data, logger)
            _parse_limits_config(config, config_data, logger)
            _parse_connection_pool_config(config, config_data, logger)
            _parse_orchestrator_config(config, config_data, logger)
            _parse_logging_config(config, config_data, base_folder, logger)
            _parse_health_config(config, config_data, logger)
        except (configparser.Error, OSError, ValueError):
            config_data.clear()
            logger.warning("Failed to parse config file %s, using defaults", config_file)

    # 2. Override with environment variables
    _apply_env_overrides(config_data, logger)

    for provider, keys in _PROVIDER_SETTINGS.items():
        if any(key in os.environ for key in keys):
            if provider == "OPENAI":
                openai_explicit = True
            else:
                perplexity_explicit = True
        key_name = keys[0]
        if key_name in os.environ and not os.environ[key_name].strip():
            if provider == "OPENAI":
                openai_key_disabled = True
            else:
                perplexity_key_disabled = True

    # Record which providers the operator explicitly selected before defaults
    # make every provider look configured.
    config_data["_OPENAI_CONFIGURED"] = _provider_has_explicit_settings(
        config_data,
        "OPENAI",
        explicit=openai_explicit,
        key_disabled=openai_key_disabled,
    )
    config_data["_PERPLEXITY_CONFIGURED"] = _provider_has_explicit_settings(
        config_data,
        "PERPLEXITY",
        explicit=perplexity_explicit,
        key_disabled=perplexity_key_disabled,
    )

    # 3. Set defaults for missing values
    _apply_config_defaults(config_data)

    return config_data


_PROVIDER_SETTINGS = {
    "OPENAI": (
        "OPENAI_API_KEY",
        "OPENAI_API_URL",
        "GPT_MODEL",
        _CONFIG_DEFAULTS["OPENAI_API_URL"],
        _CONFIG_DEFAULTS["GPT_MODEL"],
    ),
    "PERPLEXITY": (
        "PERPLEXITY_API_KEY",
        "PERPLEXITY_API_URL",
        "PERPLEXITY_MODEL",
        _CONFIG_DEFAULTS["PERPLEXITY_API_URL"],
        _CONFIG_DEFAULTS["PERPLEXITY_MODEL"],
    ),
}


def _provider_option_flags(
    config: configparser.ConfigParser,
    provider: str,
) -> tuple[bool, bool]:
    """Return whether provider options are explicit and whether its key is blank."""
    api_key, api_url, model, _default_url, _default_model = _PROVIDER_SETTINGS[provider]
    key_option = config.has_option("Default", api_key)
    key_disabled = key_option and not config.get("Default", api_key, fallback="").strip()
    explicit = any(config.has_option("Default", key) for key in (api_key, api_url, model))
    return explicit, key_disabled


def _provider_has_explicit_settings(
    config_data: dict[str, Any],
    provider: str,
    *,
    explicit: bool = False,
    key_disabled: bool = False,
) -> bool:
    """Return True when a provider was selected by key or explicit settings."""
    api_key, api_url, model, default_url, default_model = _PROVIDER_SETTINGS[provider]
    if config_data.get(api_key):
        return True
    if key_disabled:
        return False
    if explicit:
        return True
    configured_url = config_data.get(api_url)
    configured_model = config_data.get(model)
    return bool(
        (configured_url and configured_url != default_url)
        or (configured_model and configured_model != default_model)
    )


def _apply_env_overrides(config_data: dict[str, Any], logger: logging.Logger) -> None:
    """Apply environment variables to configuration."""
    env_keys = [
        "DISCORD_TOKEN",
        "ALLOWED_CHANNELS",
        "ALLOWED_CHANNEL_IDS",
        "ALLOWED_GUILDS",
        "ALLOWED_GUILD_IDS",
        "BOT_PRESENCE",
        "ACTIVITY_TYPE",
        "ACTIVITY_STATUS",
        "OPENAI_API_KEY",
        "OPENAI_API_URL",
        "PERPLEXITY_API_KEY",
        "PERPLEXITY_API_URL",
        "PERPLEXITY_MODEL",
        "GPT_MODEL",
        "INPUT_TOKENS",
        "OUTPUT_TOKENS",
        "PERPLEXITY_OUTPUT_TOKENS",
        "CONTEXT_WINDOW",
        "SYSTEM_MESSAGE",
        "RATE_LIMIT",
        "RATE_LIMIT_PER",
        "OPENAI_MAX_CONNECTIONS",
        "OPENAI_MAX_KEEPALIVE",
        "PERPLEXITY_MAX_CONNECTIONS",
        "PERPLEXITY_MAX_KEEPALIVE",
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
        "MAX_HISTORY_PER_USER",
        "CONVERSATION_TTL_SECONDS",
        "USER_LOCK_CLEANUP_INTERVAL",
        "ROUTER_MODE",
        "ROUTER_WEB_THRESHOLD_CHANNEL",
        "ROUTER_WEB_THRESHOLD_ANNOUNCE",
        "ROUTER_WEB_THRESHOLD_DM",
        "ENTITY_DETECTION_MIN_WORDS",
        "MAX_URLS_PER_MESSAGE",
        "MAX_TOTAL_SCRAPED_CHARS",
        "SCRAPE_DEADLINE_SECONDS",
        "LOG_FILE",
        "LOG_LEVEL",
        "DISCORDIANAI_LOG_COLOR",
        "HEALTH_ENABLED",
        "HEALTH_HOST",
        "HEALTH_PORT",
    ]

    for key in env_keys:
        value = os.environ.get(key)
        if value is not None:
            _apply_single_env_override(config_data, key, value, logger)


def _apply_single_env_override(
    config_data: dict[str, Any], key: str, value: str, logger: logging.Logger
) -> None:
    """Apply a single environment variable override."""
    int_keys = {
        "INPUT_TOKENS",
        "OUTPUT_TOKENS",
        "PERPLEXITY_OUTPUT_TOKENS",
        "CONTEXT_WINDOW",
        "RATE_LIMIT",
        "RATE_LIMIT_PER",
        "OPENAI_MAX_CONNECTIONS",
        "OPENAI_MAX_KEEPALIVE",
        "PERPLEXITY_MAX_CONNECTIONS",
        "PERPLEXITY_MAX_KEEPALIVE",
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
        "MAX_HISTORY_PER_USER",
        "CONVERSATION_TTL_SECONDS",
        "USER_LOCK_CLEANUP_INTERVAL",
        "ROUTER_MODE",
        "ROUTER_WEB_THRESHOLD_CHANNEL",
        "ROUTER_WEB_THRESHOLD_ANNOUNCE",
        "ROUTER_WEB_THRESHOLD_DM",
        "ENTITY_DETECTION_MIN_WORDS",
        "MAX_URLS_PER_MESSAGE",
        "MAX_TOTAL_SCRAPED_CHARS",
        "HEALTH_PORT",
    }
    float_keys = {
        "SCRAPE_DEADLINE_SECONDS",
        "ROUTER_WEB_THRESHOLD_CHANNEL",
        "ROUTER_WEB_THRESHOLD_ANNOUNCE",
        "ROUTER_WEB_THRESHOLD_DM",
    }
    bool_keys = {"HEALTH_ENABLED", "DISCORDIANAI_LOG_COLOR"}

    if key in {"ALLOWED_CHANNELS", "ALLOWED_GUILDS"}:
        config_data[key] = (
            [c.strip().lstrip("#").strip() for c in value.split(",") if c.strip()]
            if value.strip()
            else []
        )
    elif key in {"ALLOWED_CHANNEL_IDS", "ALLOWED_GUILD_IDS"}:
        config_data[key] = _parse_channel_ids(value, logger, source=key)
    elif key in int_keys:
        try:
            config_data[key] = int(value)
        except (ValueError, TypeError):
            logger.warning("Invalid integer for %s: %s", key, value)
    elif key in float_keys:
        try:
            config_data[key] = float(value)
        except (ValueError, TypeError):
            logger.warning("Invalid number for %s: %s", key, value)
    elif key in bool_keys:
        parsed = _parse_bool(value)
        if parsed is None:
            logger.warning(
                "Invalid boolean for environment variable %s=%r; accepted values are %s; "
                "ignoring override",
                key,
                value,
                _BOOLEAN_ACCEPTED_FORMS,
            )
        else:
            config_data[key] = parsed
    else:
        config_data[key] = value


def _apply_config_defaults(config_data: dict[str, Any]) -> None:
    """Apply default values for missing configuration keys."""
    for key, value in _CONFIG_DEFAULTS.items():
        if key not in config_data or config_data[key] is None:
            config_data[key] = list(value) if isinstance(value, list) else value

    # PERPLEXITY_OUTPUT_TOKENS defaults to the configured OpenAI cap, not a
    # fixed number, so existing configurations keep the same behaviour.
    if config_data.get("PERPLEXITY_OUTPUT_TOKENS") is None:
        config_data["PERPLEXITY_OUTPUT_TOKENS"] = config_data.get(
            "OUTPUT_TOKENS", DEFAULT_PERPLEXITY_OUTPUT_TOKENS
        )


def _parse_limits_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Limits section of configuration."""
    config_data["RATE_LIMIT"] = _get_int_safe(
        config,
        "RATE_LIMIT",
        _CONFIG_DEFAULTS["RATE_LIMIT"],
        logger,
        section="Limits",
    )
    config_data["RATE_LIMIT_PER"] = _get_int_safe(
        config,
        "RATE_LIMIT_PER",
        _CONFIG_DEFAULTS["RATE_LIMIT_PER"],
        logger,
        section="Limits",
    )


def _parse_connection_pool_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse ConnectionPool section of configuration."""
    config_data["OPENAI_MAX_CONNECTIONS"] = _get_int_safe(
        config,
        "OPENAI_MAX_CONNECTIONS",
        _CONFIG_DEFAULTS["OPENAI_MAX_CONNECTIONS"],
        logger,
        section="ConnectionPool",
    )
    config_data["OPENAI_MAX_KEEPALIVE"] = _get_int_safe(
        config,
        "OPENAI_MAX_KEEPALIVE",
        _CONFIG_DEFAULTS["OPENAI_MAX_KEEPALIVE"],
        logger,
        section="ConnectionPool",
    )
    config_data["PERPLEXITY_MAX_CONNECTIONS"] = _get_int_safe(
        config,
        "PERPLEXITY_MAX_CONNECTIONS",
        _CONFIG_DEFAULTS["PERPLEXITY_MAX_CONNECTIONS"],
        logger,
        section="ConnectionPool",
    )
    config_data["PERPLEXITY_MAX_KEEPALIVE"] = _get_int_safe(
        config,
        "PERPLEXITY_MAX_KEEPALIVE",
        _CONFIG_DEFAULTS["PERPLEXITY_MAX_KEEPALIVE"],
        logger,
        section="ConnectionPool",
    )


def _parse_orchestrator_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Orchestrator section of configuration."""
    config_data["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] = _get_int_safe(
        config,
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
        _CONFIG_DEFAULTS["LOOKBACK_MESSAGES_FOR_CONSISTENCY"],
        logger,
        section="Orchestrator",
    )
    config_data["MAX_HISTORY_PER_USER"] = _get_int_safe(
        config,
        "MAX_HISTORY_PER_USER",
        _CONFIG_DEFAULTS["MAX_HISTORY_PER_USER"],
        logger,
        section="Orchestrator",
    )
    config_data["CONVERSATION_TTL_SECONDS"] = _get_int_safe(
        config,
        "CONVERSATION_TTL_SECONDS",
        _CONFIG_DEFAULTS["CONVERSATION_TTL_SECONDS"],
        logger,
        section="Orchestrator",
    )
    config_data["USER_LOCK_CLEANUP_INTERVAL"] = _get_int_safe(
        config,
        "USER_LOCK_CLEANUP_INTERVAL",
        _CONFIG_DEFAULTS["USER_LOCK_CLEANUP_INTERVAL"],
        logger,
        section="Orchestrator",
    )
    config_data["ENTITY_DETECTION_MIN_WORDS"] = _get_int_safe(
        config,
        "ENTITY_DETECTION_MIN_WORDS",
        _CONFIG_DEFAULTS["ENTITY_DETECTION_MIN_WORDS"],
        logger,
        section="Orchestrator",
    )
    config_data["ROUTER_MODE"] = config.get(
        "Orchestrator",
        "ROUTER_MODE",
        fallback=_CONFIG_DEFAULTS["ROUTER_MODE"],
    )
    for key in (
        "ROUTER_WEB_THRESHOLD_CHANNEL",
        "ROUTER_WEB_THRESHOLD_ANNOUNCE",
        "ROUTER_WEB_THRESHOLD_DM",
    ):
        config_data[key] = _get_float_safe(
            config,
            key,
            _CONFIG_DEFAULTS[key],
            logger,
            section="Orchestrator",
        )


def _parse_logging_config(
    config: configparser.ConfigParser,
    config_data: dict[str, Any],
    base_folder: str | None,
    logger: logging.Logger,
) -> None:
    """Parse Logging section of configuration."""
    config_data["LOG_FILE"] = config.get(
        "Logging", "LOG_FILE", fallback=_CONFIG_DEFAULTS["LOG_FILE"]
    )
    if base_folder and not Path(config_data["LOG_FILE"]).is_absolute():
        config_data["LOG_FILE"] = str(Path(base_folder) / config_data["LOG_FILE"])
    config_data["LOG_LEVEL"] = config.get(
        "Logging", "LOG_LEVEL", fallback=_CONFIG_DEFAULTS["LOG_LEVEL"]
    )
    config_data["DISCORDIANAI_LOG_COLOR"] = _get_bool_safe(
        config,
        "DISCORDIANAI_LOG_COLOR",
        _CONFIG_DEFAULTS["DISCORDIANAI_LOG_COLOR"],
        logger,
        section="Logging",
    )


def _parse_health_config(
    config: configparser.ConfigParser,
    config_data: dict[str, Any],
    logger: logging.Logger,
) -> None:
    """Parse Health section of configuration."""
    config_data["HEALTH_ENABLED"] = _get_bool_safe(
        config,
        "HEALTH_ENABLED",
        _CONFIG_DEFAULTS["HEALTH_ENABLED"],
        logger,
        section="Health",
    )
    config_data["HEALTH_HOST"] = config.get(
        "Health", "HEALTH_HOST", fallback=_CONFIG_DEFAULTS["HEALTH_HOST"]
    )
    config_data["HEALTH_PORT"] = _get_int_safe(
        config,
        "HEALTH_PORT",
        _CONFIG_DEFAULTS["HEALTH_PORT"],
        logger,
        section="Health",
    )
    config_data["HEALTH_PROVIDER_STALE_SECONDS"] = _get_int_safe(
        config,
        "HEALTH_PROVIDER_STALE_SECONDS",
        _CONFIG_DEFAULTS["HEALTH_PROVIDER_STALE_SECONDS"],
        logger,
        section="Health",
    )


def _parse_discord_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Discord section of configuration."""
    config_data["DISCORD_TOKEN"] = config.get(
        "Discord", "DISCORD_TOKEN", fallback=_CONFIG_DEFAULTS["DISCORD_TOKEN"]
    )
    channels_str = config.get("Discord", "ALLOWED_CHANNELS", fallback="")
    config_data["ALLOWED_CHANNELS"] = [c.strip() for c in channels_str.split(",") if c.strip()]
    channel_ids_str = config.get("Discord", "ALLOWED_CHANNEL_IDS", fallback="")
    config_data["ALLOWED_CHANNEL_IDS"] = _parse_channel_ids(
        channel_ids_str,
        logger,
        source="Discord.ALLOWED_CHANNEL_IDS",
    )
    guilds_str = config.get("Discord", "ALLOWED_GUILDS", fallback="")
    config_data["ALLOWED_GUILDS"] = [
        g.strip().lstrip("#").strip() for g in guilds_str.split(",") if g.strip()
    ]
    guild_ids_str = config.get("Discord", "ALLOWED_GUILD_IDS", fallback="")
    config_data["ALLOWED_GUILD_IDS"] = _parse_channel_ids(
        guild_ids_str,
        logger,
        source="Discord.ALLOWED_GUILD_IDS",
    )
    config_data["BOT_PRESENCE"] = config.get(
        "Discord", "BOT_PRESENCE", fallback=_CONFIG_DEFAULTS["BOT_PRESENCE"]
    )
    config_data["ACTIVITY_TYPE"] = config.get(
        "Discord", "ACTIVITY_TYPE", fallback=_CONFIG_DEFAULTS["ACTIVITY_TYPE"]
    )
    config_data["ACTIVITY_STATUS"] = config.get(
        "Discord", "ACTIVITY_STATUS", fallback=_CONFIG_DEFAULTS["ACTIVITY_STATUS"]
    )


def _parse_default_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Default section of configuration."""
    config_data["OPENAI_API_KEY"] = config.get(
        "Default", "OPENAI_API_KEY", fallback=_CONFIG_DEFAULTS["OPENAI_API_KEY"]
    )
    config_data["OPENAI_API_URL"] = config.get(
        "Default", "OPENAI_API_URL", fallback=_CONFIG_DEFAULTS["OPENAI_API_URL"]
    )
    config_data["GPT_MODEL"] = config.get(
        "Default", "GPT_MODEL", fallback=_CONFIG_DEFAULTS["GPT_MODEL"]
    )

    # Perplexity API
    config_data["PERPLEXITY_API_KEY"] = config.get(
        "Default", "PERPLEXITY_API_KEY", fallback=_CONFIG_DEFAULTS["PERPLEXITY_API_KEY"]
    )
    config_data["PERPLEXITY_API_URL"] = config.get(
        "Default", "PERPLEXITY_API_URL", fallback=_CONFIG_DEFAULTS["PERPLEXITY_API_URL"]
    )
    config_data["PERPLEXITY_MODEL"] = config.get(
        "Default", "PERPLEXITY_MODEL", fallback=_CONFIG_DEFAULTS["PERPLEXITY_MODEL"]
    )

    settings = ["INPUT_TOKENS", "OUTPUT_TOKENS", "CONTEXT_WINDOW"]
    for key in settings:
        config_data[key] = _get_int_safe(config, key, _CONFIG_DEFAULTS[key], logger)

    # An omitted Perplexity cap follows OUTPUT_TOKENS (applied after all
    # overrides); an explicit value is validated and honoured on its own.
    raw_perplexity_output = config.get("Default", "PERPLEXITY_OUTPUT_TOKENS", fallback=None)
    if raw_perplexity_output is not None:
        try:
            config_data["PERPLEXITY_OUTPUT_TOKENS"] = int(raw_perplexity_output)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid PERPLEXITY_OUTPUT_TOKENS value %r; using OUTPUT_TOKENS",
                raw_perplexity_output,
            )

    config_data["SYSTEM_MESSAGE"] = config.get(
        "Default", "SYSTEM_MESSAGE", fallback=_CONFIG_DEFAULTS["SYSTEM_MESSAGE"]
    )


def _parse_scraping_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse web scraping budget settings from configuration."""
    config_data["MAX_URLS_PER_MESSAGE"] = _get_int_safe(
        config,
        "MAX_URLS_PER_MESSAGE",
        _CONFIG_DEFAULTS["MAX_URLS_PER_MESSAGE"],
        logger,
    )
    config_data["MAX_TOTAL_SCRAPED_CHARS"] = _get_int_safe(
        config,
        "MAX_TOTAL_SCRAPED_CHARS",
        _CONFIG_DEFAULTS["MAX_TOTAL_SCRAPED_CHARS"],
        logger,
    )
    config_data["SCRAPE_DEADLINE_SECONDS"] = _get_float_safe(
        config,
        "SCRAPE_DEADLINE_SECONDS",
        _CONFIG_DEFAULTS["SCRAPE_DEADLINE_SECONDS"],
        logger,
    )


def _get_int_safe(
    config: configparser.ConfigParser,
    key: str,
    default: int,
    logger: logging.Logger,
    section: str = "Default",
) -> int:
    """Safely get an integer from configuration with fallback."""
    try:
        return config.getint(section, key, fallback=default)
    except ValueError:
        logger.warning("Invalid %s value, using default %d", key, default)
        return default


_BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on"}
_BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off"}
_BOOLEAN_ACCEPTED_FORMS = "1/yes/true/on or 0/no/false/off"


def _parse_bool(value: str) -> bool | None:
    """Parse a boolean string, returning None when the value is not accepted."""
    normalized = value.strip().lower()
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    return None


def _get_bool_safe(
    config: configparser.ConfigParser,
    key: str,
    default: bool,
    logger: logging.Logger,
    section: str = "Default",
) -> bool:
    """Safely get a boolean from configuration with fallback."""
    raw_value = config.get(section, key, fallback=None)
    if raw_value is None:
        return default

    try:
        return config.getboolean(section, key, fallback=default)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid boolean for [%s] %s=%r; accepted values are %s; using default %s",
            section,
            key,
            raw_value,
            _BOOLEAN_ACCEPTED_FORMS,
            default,
        )
        return default


def _get_float_safe(
    config: configparser.ConfigParser,
    key: str,
    default: float,
    logger: logging.Logger,
    section: str = "Default",
) -> float:
    """Safely get a floating-point value from configuration with fallback."""
    try:
        return config.getfloat(section, key, fallback=default)
    except ValueError:
        logger.warning("Invalid %s value, using default %s", key, default)
        return default


def _parse_channel_ids(value: str, logger: logging.Logger, source: str) -> list[int]:
    """Parse a comma-separated list of Discord channel IDs."""
    channel_ids: list[int] = []
    for token in value.split(","):
        stripped = token.strip()
        if not stripped:
            continue
        try:
            channel_ids.append(int(stripped))
        except ValueError:
            logger.warning("Invalid integer in %s: %s", source, stripped)
    return channel_ids


def get_error_messages() -> dict[str, str]:
    """Get standardized error messages for consistent user experience.

    Returns:
        Dict[str, str]: Dictionary of error message keys to user-friendly messages.
    """
    return ERROR_MESSAGES.copy()
