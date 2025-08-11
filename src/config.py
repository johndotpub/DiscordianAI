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

# API Configuration Constants
OPENAI_VALID_MODELS = [
    "gpt-5",  # Latest generation
    "gpt-4o",  # GPT-4 series - current
    "gpt-4o-mini",  # GPT-4 series - cost-effective
    "gpt-4",  # GPT-4 series - previous generation
    "gpt-4-turbo",  # GPT-4 series - enhanced
]


PERPLEXITY_MODELS = ["sonar-pro", "sonar"]  # Latest Perplexity model  # General Perplexity model

DISCORD_ACTIVITY_TYPES = ["playing", "streaming", "listening", "watching", "custom", "competing"]

# API URL Patterns for validation
VALID_OPENAI_URL_PATTERN = re.compile(r"https://api\.openai\.com/v\d+/?")
VALID_PERPLEXITY_URL_PATTERN = re.compile(r"https://api\.perplexity\.ai/?")

# Default API URLs
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/"
DEFAULT_PERPLEXITY_API_URL = "https://api.perplexity.ai"

# Performance and Caching Constants
DEFAULT_CACHE_TTL = 300.0  # 5 minutes
DEFAULT_CACHE_SIZE = 1000
DEFAULT_CONVERSATION_CACHE_TTL = 1800.0  # 30 minutes
DEFAULT_HEALTH_CHECK_INTERVAL = 300  # 5 minutes

# Rate Limiting Constants
DEFAULT_RATE_LIMIT = 10
DEFAULT_RATE_LIMIT_PER = 60  # seconds

# Orchestrator Constants
DEFAULT_LOOKBACK_MESSAGES_FOR_CONSISTENCY = 6
DEFAULT_ENTITY_DETECTION_MIN_WORDS = 10
DEFAULT_MAX_HISTORY_PER_USER = 50
DEFAULT_USER_LOCK_CLEANUP_INTERVAL = 3600  # 1 hour

# Token and Context Constants
DEFAULT_INPUT_TOKENS = 120000
DEFAULT_OUTPUT_TOKENS = 8000
DEFAULT_CONTEXT_WINDOW = 128000

# Discord Message Constants
DISCORD_MAX_MESSAGE_LENGTH = 2000
DISCORD_MAX_EMBED_DESCRIPTION = 4096
DISCORD_MAX_RECURSION_DEPTH = 10

# Time-sensitive query patterns for caching decisions
TIME_SENSITIVITY_PATTERNS = [
    r"\b(current|now|today|yesterday|tomorrow|this\s+(morning|afternoon|evening)|tonight)\b",
    r"\b(latest|recent|breaking|live|real\s*time)\b",
    r"\b(what\s+time|what\s+date|when\s+is)\b",
    r"\b(stock\s+(price|market)|crypto\s+price)\b",
]

# Factual query patterns for routing decisions
FACTUAL_PATTERNS = [
    r"\b(what\s+is|define|explain|describe)\b",
    r"\b(how\s+(do|does|to|can|much|many))\b",
    r"\b(where\s+(is|are|can|do))\b",
    r"\b(when\s+(is|are|was|were|did))\b",
    r"\b(who\s+(is|are|was|were))\b",
    r"\b(which\s+(is|are))\b",
]

# Conversational query patterns
CONVERSATIONAL_PATTERNS = [
    r"\b(tell\s+me\s+about|talk\s+about)\b",
    r"\b(i\s+(think|feel|believe|wonder))\b",
    r"\b(what\s+do\s+you\s+(think|feel|recommend))\b",
    r"\b(can\s+you\s+(help|write|create|make))\b",
]

# Entity detection patterns for web search routing
ENTITY_PATTERNS = [
    r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",  # Proper names
    r"\b\d{4}\b",  # Years
    r"\$[0-9,]+(?:\.[0-9]{2})?\b",  # Dollar amounts
]

# Regex patterns for message processing (compiled for performance)
CITATION_PATTERN = re.compile(r"\[(\d+)\]")
URL_PATTERN = re.compile(r"https?://[^\s\[\]()]+[^\s\[\]().,;!?]")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BARE_URL_PATTERN = re.compile(r"https?://[^\s]+")
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

# Error messages for user-facing responses
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

    # If base_folder is provided, resolve config_file and log file paths
    if base_folder and config_file and not Path(config_file).is_absolute():
        config_file = str(Path(base_folder) / config_file)

    # 1. Load from file if provided and exists
    if config_file and Path(config_file).exists():
        config.read(config_file)
        # Discord section
        config_data["DISCORD_TOKEN"] = config.get("Discord", "DISCORD_TOKEN", fallback=None)
        config_data["ALLOWED_CHANNELS"] = config.get(
            "Discord", "ALLOWED_CHANNELS", fallback=""
        ).split(",")
        config_data["BOT_PRESENCE"] = config.get("Discord", "BOT_PRESENCE", fallback="online")
        config_data["ACTIVITY_TYPE"] = config.get("Discord", "ACTIVITY_TYPE", fallback="listening")
        config_data["ACTIVITY_STATUS"] = config.get(
            "Discord", "ACTIVITY_STATUS", fallback="Humans"
        )
        # Default section
        config_data["OPENAI_API_KEY"] = config.get("Default", "OPENAI_API_KEY", fallback=None)
        config_data["OPENAI_API_URL"] = config.get(
            "Default", "OPENAI_API_URL", fallback="https://api.openai.com/v1/"
        )
        # Perplexity API for web search
        config_data["PERPLEXITY_API_KEY"] = config.get(
            "Default", "PERPLEXITY_API_KEY", fallback=None
        )
        config_data["PERPLEXITY_API_URL"] = config.get(
            "Default", "PERPLEXITY_API_URL", fallback="https://api.perplexity.ai"
        )
        config_data["PERPLEXITY_MODEL"] = config.get(
            "Default", "PERPLEXITY_MODEL", fallback="sonar-pro"
        )
        config_data["GPT_MODEL"] = config.get("Default", "GPT_MODEL", fallback="gpt-4o-mini")
        config_data["INPUT_TOKENS"] = config.getint("Default", "INPUT_TOKENS", fallback=120000)
        config_data["OUTPUT_TOKENS"] = config.getint("Default", "OUTPUT_TOKENS", fallback=8000)
        config_data["CONTEXT_WINDOW"] = config.getint("Default", "CONTEXT_WINDOW", fallback=128000)
        config_data["SYSTEM_MESSAGE"] = config.get(
            "Default", "SYSTEM_MESSAGE", fallback="You are a helpful assistant."
        )
        # Removed unsupported GPT-5 parameters
        # Limits section
        config_data["RATE_LIMIT"] = config.getint("Limits", "RATE_LIMIT", fallback=10)
        config_data["RATE_LIMIT_PER"] = config.getint("Limits", "RATE_LIMIT_PER", fallback=60)
        # Orchestrator section
        config_data["LOOKBACK_MESSAGES_FOR_CONSISTENCY"] = config.getint(
            "Orchestrator", "LOOKBACK_MESSAGES_FOR_CONSISTENCY", fallback=6
        )
        config_data["ENTITY_DETECTION_MIN_WORDS"] = config.getint(
            "Orchestrator", "ENTITY_DETECTION_MIN_WORDS", fallback=10
        )
        config_data["MAX_HISTORY_PER_USER"] = config.getint(
            "Orchestrator", "MAX_HISTORY_PER_USER", fallback=50
        )
        config_data["USER_LOCK_CLEANUP_INTERVAL"] = config.getint(
            "Orchestrator", "USER_LOCK_CLEANUP_INTERVAL", fallback=3600
        )
        # Logging section
        config_data["LOG_FILE"] = config.get("Logging", "LOG_FILE", fallback="bot.log")
        if base_folder and not Path(config_data["LOG_FILE"]).is_absolute():
            config_data["LOG_FILE"] = str(Path(base_folder) / config_data["LOG_FILE"])
        config_data["LOG_LEVEL"] = config.get("Logging", "LOG_LEVEL", fallback="INFO")

    # 2. Override with environment variables if set
    env_overrides = {
        "DISCORD_TOKEN": os.environ.get("DISCORD_TOKEN"),
        "ALLOWED_CHANNELS": os.environ.get("ALLOWED_CHANNELS"),
        "BOT_PRESENCE": os.environ.get("BOT_PRESENCE"),
        "ACTIVITY_TYPE": os.environ.get("ACTIVITY_TYPE"),
        "ACTIVITY_STATUS": os.environ.get("ACTIVITY_STATUS"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_API_URL": os.environ.get("OPENAI_API_URL"),
        "PERPLEXITY_API_KEY": os.environ.get("PERPLEXITY_API_KEY"),
        "PERPLEXITY_API_URL": os.environ.get("PERPLEXITY_API_URL"),
        "PERPLEXITY_MODEL": os.environ.get("PERPLEXITY_MODEL"),
        "GPT_MODEL": os.environ.get("GPT_MODEL"),
        "INPUT_TOKENS": os.environ.get("INPUT_TOKENS"),
        "OUTPUT_TOKENS": os.environ.get("OUTPUT_TOKENS"),
        "CONTEXT_WINDOW": os.environ.get("CONTEXT_WINDOW"),
        "SYSTEM_MESSAGE": os.environ.get("SYSTEM_MESSAGE"),
        # Removed unsupported GPT-5 parameters
        "RATE_LIMIT": os.environ.get("RATE_LIMIT"),
        "RATE_LIMIT_PER": os.environ.get("RATE_LIMIT_PER"),
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY": os.environ.get("LOOKBACK_MESSAGES_FOR_CONSISTENCY"),
        "ENTITY_DETECTION_MIN_WORDS": os.environ.get("ENTITY_DETECTION_MIN_WORDS"),
        "MAX_HISTORY_PER_USER": os.environ.get("MAX_HISTORY_PER_USER"),
        "USER_LOCK_CLEANUP_INTERVAL": os.environ.get("USER_LOCK_CLEANUP_INTERVAL"),
        "LOG_FILE": os.environ.get("LOG_FILE"),
        "LOG_LEVEL": os.environ.get("LOG_LEVEL"),
    }
    for key, value in env_overrides.items():
        if value is not None:
            if key == "ALLOWED_CHANNELS":
                config_data[key] = value.split(",")
            elif key in {
                "INPUT_TOKENS",
                "OUTPUT_TOKENS",
                "CONTEXT_WINDOW",
                "RATE_LIMIT",
                "RATE_LIMIT_PER",
                "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
                "ENTITY_DETECTION_MIN_WORDS",
                "MAX_HISTORY_PER_USER",
                "USER_LOCK_CLEANUP_INTERVAL",
            }:
                try:
                    config_data[key] = int(value)
                except ValueError:
                    # Log warning for invalid integer values but continue with defaults
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Invalid integer value for a configuration key, using default instead"
                    )
            else:
                config_data[key] = value

    # 3. Set defaults if still missing
    defaults = {
        # Discord Configuration
        "DISCORD_TOKEN": None,
        "ALLOWED_CHANNELS": [],
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "listening",
        "ACTIVITY_STATUS": "Humans",
        # AI Service Configuration
        "OPENAI_API_KEY": None,
        "OPENAI_API_URL": "https://api.openai.com/v1/",
        "PERPLEXITY_API_KEY": None,
        "PERPLEXITY_API_URL": "https://api.perplexity.ai",
        "PERPLEXITY_MODEL": "sonar-pro",
        "GPT_MODEL": "gpt-4o-mini",
        "INPUT_TOKENS": 120000,
        "OUTPUT_TOKENS": 8000,
        "CONTEXT_WINDOW": 128000,
        "SYSTEM_MESSAGE": "You are a helpful assistant.",
        # Removed unsupported GPT-5 parameters
        # Rate Limiting Configuration
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        # Logging Configuration
        "LOG_FILE": "bot.log",
        "LOG_LEVEL": "INFO",
        # AI Orchestrator Configuration
        # How many recent messages to check for AI service consistency
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY": 6,
        # Minimum words before checking for entities in routing decisions
        "ENTITY_DETECTION_MIN_WORDS": 10,
        "MAX_HISTORY_PER_USER": 50,  # Maximum conversation entries per user before pruning
        "USER_LOCK_CLEANUP_INTERVAL": 3600,  # How often to clean up inactive user locks (seconds)
    }
    for key, value in defaults.items():
        if key not in config_data or config_data[key] is None:
            config_data[key] = value

    return config_data


def get_error_messages() -> dict[str, str]:
    """Get standardized error messages for consistent user experience.

    Returns:
        Dict[str, str]: Dictionary of error message keys to user-friendly messages.
    """
    return {
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
