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
OPENAI_MODEL_PREFIX = "gpt-5"

# Canonical GPT-5 model identifiers that we document. Snapshot variants are allowed via regex.
OPENAI_VALID_MODELS = [
    OPENAI_MODEL_PREFIX,  # Latest generation - standard
    "gpt-5-mini",  # Latest generation - cost-effective
    "gpt-5-nano",  # Latest generation - high-speed
    "gpt-5-chat",  # Latest generation - conversational
]


# Perplexity Models
PERPLEXITY_MODELS = ["sonar-pro", "sonar"]  # Latest Perplexity model


SNAPSHOT_MODEL_PREFIX = f"{OPENAI_MODEL_PREFIX}."


def is_supported_openai_model(model: str | None) -> bool:
    """Return True if the provided GPT model matches supported GPT-5 identifiers."""
    if not model:
        return False

    if model in OPENAI_VALID_MODELS:
        return True

    # Snapshot builds arrive as dotted identifiers (e.g., gpt-5.2025-02-18, gpt-5.1).
    return bool(model.startswith(SNAPSHOT_MODEL_PREFIX))


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

# Discord Message Constants
MESSAGE_LIMIT = 2000  # Discord's hard limit for regular messages
MESSAGE_BUFFER = 100
EMBED_LIMIT = 4096  # Discord's hard limit for embed descriptions
EMBED_SAFE_LIMIT = 3840  # Safe margin for citation expansion and formatting
MAX_SPLIT_RECURSION = 10  # Safety limit for message splitting recursion

# ============================================================================
# PERFORMANCE & CACHING
# ============================================================================

# Cache Configuration
DEFAULT_CACHE_TTL = 300.0  # 5 minutes
DEFAULT_CACHE_SIZE = 1000
DEFAULT_CONVERSATION_CACHE_TTL = 1800.0  # 30 minutes
DEFAULT_HEALTH_CHECK_INTERVAL = 300  # 5 minutes

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
DEFAULT_USER_LOCK_CLEANUP_INTERVAL = 3600  # 1 hour

# Token and Context Limits
DEFAULT_INPUT_TOKENS = 120000
DEFAULT_OUTPUT_TOKENS = 8000
DEFAULT_CONTEXT_WINDOW = 128000

# ============================================================================
# SMART ROUTING PATTERNS
# ============================================================================

# Time-sensitive query patterns for web search routing
TIME_SENSITIVITY_PATTERNS = [
    r"\b(today|yesterday|this week|this month|this year|recently|latest|current|now)\b",
    r"\b(2024|2025|2026)\b",  # Recent/current years
    r"\b(what.*happening|what.*happened)\b",
    r"\b(current|recent|new|latest).*\b(news|update|information|data|report)\b",
]

# Factual query patterns for web search routing
FACTUAL_PATTERNS = [
    r"\b(what|who|when|where|how much|how many).*\b(is|are|was|were|will|would|cost|price)\b",
    r"\b(weather|temperature|forecast|stock|price|market|news|events|schedule|score|game)\b",
    r"\b(status|condition|situation|state).*of\b",
    r"\bhow.*doing\b",
    r"\b(better|worse|faster|slower|higher|lower|more|less).*than\b",
]

# Conversational/creative patterns for OpenAI routing
CONVERSATIONAL_PATTERNS = [
    r"\b(hello|hi|hey|good morning|good evening|how are you|what's up)\b",
    r"\b(what do you think|your opinion|do you like|do you prefer)\b",
    r"\b(write|create|make|generate|tell me).*\b(story|poem|joke|song|script)\b",
    r"\b(how to|help me|explain|teach|show me).*\b(code|program|function|algorithm)\b",
    r"\b(meaning|purpose|philosophy|theory|concept|idea)\b",
]

# Entity detection patterns for web search routing
ENTITY_PATTERNS = [
    r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",  # Proper names
    r"\b[A-Z]{2,}\b",  # Acronyms/companies
    r"\$[A-Z]+\b",  # Stock symbols
]

# Follow-up detection patterns for conversation consistency
FOLLOW_UP_PATTERNS = [
    r"\b(continue|more|follow.?up|also|additionally|furthermore|moreover)\b",
    r"\b(what about|how about|tell me more)\b",
    r"^(yes|no|ok|okay),",  # Responses that continue conversation
    # More specific: "and what about...", "but how..."
    r"\b(and|but|however|though|although)\b\s+\w+\s*\?",
]

# ============================================================================
# VALIDATION THRESHOLDS
# ============================================================================

MAX_OUTPUT_TOKENS_THRESHOLD = 50000
MAX_INPUT_TOKENS_THRESHOLD = 200000
MAX_RATE_LIMIT_THRESHOLD = 100
MAX_RECOMMENDED_REQ_PER_MIN = 60
SECONDS_PER_MINUTE = 60

# ============================================================================
# COMPILED PATTERNS (for performance)
# ============================================================================

# Smart routing patterns (used by smart orchestrator)
COMPILED_TIME_SENSITIVITY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in TIME_SENSITIVITY_PATTERNS
]
COMPILED_FACTUAL_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in FACTUAL_PATTERNS]
COMPILED_CONVERSATIONAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in CONVERSATIONAL_PATTERNS
]
COMPILED_ENTITY_PATTERNS = [re.compile(pattern) for pattern in ENTITY_PATTERNS]
COMPILED_FOLLOW_UP_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in FOLLOW_UP_PATTERNS
]

# ============================================================================
# MESSAGE PROCESSING PATTERNS
# ============================================================================

# Citation and mention patterns
CITATION_PATTERN = re.compile(r"\[(\d+)\]")
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

# URL detection patterns for smart routing
URL_DETECTION_PATTERNS = [
    r"https?://[^\s\[\]()]+[^\s\[\]().,;!?]",  # Standard URLs with common punctuation
    r"\[([^\]]+)\]\(([^)]+)\)",  # Markdown links [text](url)
    r"(?:https?://)?[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}"
    r"(?:/[^\s]*)?",  # Bare URLs (domain.tld/path)
]

# Compile URL detection patterns for performance
COMPILED_URL_DETECTION_PATTERNS = [re.compile(pattern) for pattern in URL_DETECTION_PATTERNS]

# Individual compiled patterns for backward compatibility and specific use cases
URL_PATTERN = COMPILED_URL_DETECTION_PATTERNS[0]  # Standard URLs
LINK_PATTERN = COMPILED_URL_DETECTION_PATTERNS[1]  # Markdown links
BARE_URL_PATTERN = COMPILED_URL_DETECTION_PATTERNS[2]  # Bare URLs

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

    # If base_folder is provided, resolve config_file and log file paths
    if base_folder and config_file and not Path(config_file).is_absolute():
        config_file = str(Path(base_folder) / config_file)

    if config_file and Path(config_file).exists():
        try:
            config.read(config_file)
            _parse_discord_config(config, config_data)
            _parse_default_config(config, config_data, logger)
            _parse_limits_config(config, config_data, logger)
            _parse_orchestrator_config(config, config_data, logger)
            _parse_logging_config(config, config_data, base_folder)
        except (configparser.Error, OSError):
            logger.warning("Failed to parse config file %s, using defaults", config_file)

    # 2. Override with environment variables
    _apply_env_overrides(config_data, logger)

    # 3. Set defaults for missing values
    _apply_config_defaults(config_data)

    return config_data


def _apply_env_overrides(config_data: dict[str, Any], logger: logging.Logger) -> None:
    """Apply environment variables to configuration."""
    env_keys = [
        "DISCORD_TOKEN",
        "ALLOWED_CHANNELS",
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
        "CONTEXT_WINDOW",
        "SYSTEM_MESSAGE",
        "RATE_LIMIT",
        "RATE_LIMIT_PER",
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
        "MAX_HISTORY_PER_USER",
        "USER_LOCK_CLEANUP_INTERVAL",
        "LOG_FILE",
        "LOG_LEVEL",
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
        "CONTEXT_WINDOW",
        "RATE_LIMIT",
        "RATE_LIMIT_PER",
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
        "MAX_HISTORY_PER_USER",
        "USER_LOCK_CLEANUP_INTERVAL",
    }

    if key == "ALLOWED_CHANNELS":
        config_data[key] = (
            [c.strip() for c in value.split(",") if c.strip()] if value.strip() else []
        )
    elif key in int_keys:
        try:
            config_data[key] = int(value)
        except (ValueError, TypeError):
            logger.warning("Invalid integer for %s: %s", key, value)
    else:
        config_data[key] = value


def _apply_config_defaults(config_data: dict[str, Any]) -> None:
    """Apply default values for missing configuration keys."""
    defaults = {
        "DISCORD_TOKEN": None,
        "ALLOWED_CHANNELS": [],
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "listening",
        "ACTIVITY_STATUS": "Humans",
        "OPENAI_API_KEY": None,
        "OPENAI_API_URL": "https://api.openai.com/v1/",
        "PERPLEXITY_API_KEY": None,
        "PERPLEXITY_API_URL": "https://api.perplexity.ai",
        "PERPLEXITY_MODEL": "sonar-pro",
        "GPT_MODEL": "gpt-5-mini",
        "INPUT_TOKENS": 120000,
        "OUTPUT_TOKENS": 8000,
        "CONTEXT_WINDOW": 128000,
        "SYSTEM_MESSAGE": "You are a helpful assistant.",
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "OPENAI_MAX_CONNECTIONS": 50,
        "OPENAI_MAX_KEEPALIVE": 10,
        "PERPLEXITY_MAX_CONNECTIONS": 30,
        "PERPLEXITY_MAX_KEEPALIVE": 5,
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY": 6,
        "MAX_HISTORY_PER_USER": 50,
        "USER_LOCK_CLEANUP_INTERVAL": 3600,
        "LOG_FILE": "bot.log",
        "LOG_LEVEL": "INFO",
    }
    for key, value in defaults.items():
        if key not in config_data or config_data[key] is None:
            config_data[key] = value


def _parse_limits_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Limits section of configuration."""
    try:
        config_data["RATE_LIMIT"] = config.getint("Limits", "RATE_LIMIT", fallback=10)
    except ValueError:
        logger.warning("Invalid RATE_LIMIT value, using default 10")
        config_data["RATE_LIMIT"] = 10
    try:
        config_data["RATE_LIMIT_PER"] = config.getint("Limits", "RATE_LIMIT_PER", fallback=60)
    except ValueError:
        logger.warning("Invalid RATE_LIMIT_PER value, using default 60")
        config_data["RATE_LIMIT_PER"] = 60


def _parse_orchestrator_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Orchestrator section of configuration."""
    try:
        config_data["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] = config.getint(
            "Orchestrator",
            "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
            fallback=6,
        )
        config_data["MAX_HISTORY_PER_USER"] = config.getint(
            "Orchestrator",
            "MAX_HISTORY_PER_USER",
            fallback=50,
        )
        config_data["USER_LOCK_CLEANUP_INTERVAL"] = config.getint(
            "Orchestrator",
            "USER_LOCK_CLEANUP_INTERVAL",
            fallback=3600,
        )
    except ValueError:
        logger.warning("Invalid Orchestrator config value, using defaults")
        config_data.setdefault("LOOKBACK_MESSAGES_FOR_CONSISTENCY", 6)
        config_data.setdefault("MAX_HISTORY_PER_USER", 50)
        config_data.setdefault("USER_LOCK_CLEANUP_INTERVAL", 3600)


def _parse_logging_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], base_folder: str | None
) -> None:
    """Parse Logging section of configuration."""
    config_data["LOG_FILE"] = config.get("Logging", "LOG_FILE", fallback="bot.log")
    if base_folder and not Path(config_data["LOG_FILE"]).is_absolute():
        config_data["LOG_FILE"] = str(Path(base_folder) / config_data["LOG_FILE"])
    config_data["LOG_LEVEL"] = config.get("Logging", "LOG_LEVEL", fallback="INFO")


def _parse_discord_config(config: configparser.ConfigParser, config_data: dict[str, Any]) -> None:
    """Parse Discord section of configuration."""
    config_data["DISCORD_TOKEN"] = config.get("Discord", "DISCORD_TOKEN", fallback=None)
    channels_str = config.get("Discord", "ALLOWED_CHANNELS", fallback="")
    config_data["ALLOWED_CHANNELS"] = [c.strip() for c in channels_str.split(",") if c.strip()]
    config_data["BOT_PRESENCE"] = config.get("Discord", "BOT_PRESENCE", fallback="online")
    config_data["ACTIVITY_TYPE"] = config.get("Discord", "ACTIVITY_TYPE", fallback="listening")
    config_data["ACTIVITY_STATUS"] = config.get("Discord", "ACTIVITY_STATUS", fallback="Humans")


def _parse_default_config(
    config: configparser.ConfigParser, config_data: dict[str, Any], logger: logging.Logger
) -> None:
    """Parse Default section of configuration."""
    config_data["OPENAI_API_KEY"] = config.get("Default", "OPENAI_API_KEY", fallback=None)
    config_data["OPENAI_API_URL"] = config.get(
        "Default", "OPENAI_API_URL", fallback="https://api.openai.com/v1/"
    )
    config_data["GPT_MODEL"] = config.get("Default", "GPT_MODEL", fallback="gpt-5-mini")

    # Perplexity API
    config_data["PERPLEXITY_API_KEY"] = config.get("Default", "PERPLEXITY_API_KEY", fallback=None)
    config_data["PERPLEXITY_API_URL"] = config.get(
        "Default", "PERPLEXITY_API_URL", fallback="https://api.perplexity.ai"
    )
    config_data["PERPLEXITY_MODEL"] = config.get(
        "Default", "PERPLEXITY_MODEL", fallback="sonar-pro"
    )

    settings = [
        ("INPUT_TOKENS", 120000),
        ("OUTPUT_TOKENS", 8000),
        ("CONTEXT_WINDOW", 128000),
    ]
    for key, default in settings:
        config_data[key] = _get_int_safe(config, key, default, logger)

    config_data["SYSTEM_MESSAGE"] = config.get(
        "Default", "SYSTEM_MESSAGE", fallback="You are a helpful assistant."
    )


def _get_int_safe(
    config: configparser.ConfigParser, key: str, default: int, logger: logging.Logger
) -> int:
    """Safely get an integer from configuration with fallback."""
    try:
        return config.getint("Default", key, fallback=default)
    except ValueError:
        logger.warning("Invalid %s value, using default %d", key, default)
        return default


def get_error_messages() -> dict[str, str]:
    """Get standardized error messages for consistent user experience.

    Returns:
        Dict[str, str]: Dictionary of error message keys to user-friendly messages.
    """
    return ERROR_MESSAGES.copy()
