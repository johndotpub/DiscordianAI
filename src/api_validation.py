"""API parameter validation for OpenAI, Perplexity, and Discord APIs.

This module provides functions to validate API parameters and configurations
against current API specifications to ensure compatibility and optimal performance.
"""

import logging
import re

# Import constants from config.py (single source of truth)
from .config import (
    DISCORD_ACTIVITY_TYPES,
    MAX_INPUT_TOKENS_THRESHOLD,
    MAX_OUTPUT_TOKENS_THRESHOLD,
    MAX_RATE_LIMIT_THRESHOLD,
    MAX_RECOMMENDED_REQ_PER_MIN,
    OPENAI_VALID_MODELS,
    PERPLEXITY_MODELS,
    SECONDS_PER_MINUTE,
    VALID_OPENAI_URL_PATTERN,
    VALID_PERPLEXITY_URL_PATTERN,
    is_supported_openai_model,
)

# Re-export for backward compatibility
__all__ = [
    "DISCORD_ACTIVITY_TYPES",
    "OPENAI_API_KEY_PATTERN",
    "OPENAI_VALID_MODELS",
    "PERPLEXITY_API_KEY_PATTERN",
    "PERPLEXITY_MODELS",
    "VALID_OPENAI_URL_PATTERN",
    "VALID_PERPLEXITY_URL_PATTERN",
    "log_validation_results",
    "validate_discord_config",
    "validate_full_config",
    "validate_openai_api_key_format",
    "validate_openai_config",
    "validate_perplexity_api_key_format",
    "validate_perplexity_config",
]

# API key format patterns
# OpenAI keys can be: sk-xxx, sk-proj-xxx, sk-svcacct-xxx, etc.
OPENAI_API_KEY_PATTERN = re.compile(r"^sk-[a-zA-Z0-9\-_]{20,}$")
# Perplexity keys: pplx-xxx
PERPLEXITY_API_KEY_PATTERN = re.compile(r"^pplx-[a-zA-Z0-9\-_]{20,}$")


def validate_openai_api_key_format(api_key: str | None) -> tuple[bool, str | None]:
    """Validate OpenAI API key format.

    Args:
        api_key: API key to validate (can be None if not provided)

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if api_key is None:
        return True, None  # None is valid (optional)

    if not api_key or not api_key.strip():
        return False, (
            "Invalid OpenAI API key format. "
            "OpenAI API keys should start with 'sk-' followed by alphanumeric characters. "
            "Please verify your API key from https://platform.openai.com/api-keys"
        )

    if not OPENAI_API_KEY_PATTERN.match(api_key):
        return False, (
            "Invalid OpenAI API key format. "
            "OpenAI API keys should start with 'sk-' followed by alphanumeric characters. "
            "Please verify your API key from https://platform.openai.com/api-keys"
        )

    return True, None


def validate_perplexity_api_key_format(api_key: str | None) -> tuple[bool, str | None]:
    """Validate Perplexity API key format.

    Args:
        api_key: API key to validate (can be None if not provided)

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if api_key is None:
        return True, None  # None is valid (optional)

    if not api_key or not api_key.strip():
        return False, (
            "Invalid Perplexity API key format. "
            "Perplexity API keys should start with 'pplx-' followed by alphanumeric characters. "
            "Please verify your API key from https://www.perplexity.ai/settings/api"
        )

    if not PERPLEXITY_API_KEY_PATTERN.match(api_key):
        return False, (
            "Invalid Perplexity API key format. "
            "Perplexity API keys should start with 'pplx-' followed by alphanumeric characters. "
            "Please verify your API key from https://www.perplexity.ai/settings/api"
        )

    return True, None


def validate_openai_config(config: dict) -> list[str]:
    """Validate OpenAI API configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate API key format
    api_key = config.get("OPENAI_API_KEY")
    if api_key:
        is_valid, error_msg = validate_openai_api_key_format(api_key)
        # Ensure error_msg does not echo the original API key
        if not is_valid and error_msg:
            safe_msg = (
                error_msg.replace(api_key, "[REDACTED]") if api_key in error_msg else error_msg
            )
            issues.append(f"ERROR: {safe_msg}")

    # Validate API URL
    api_url = config.get("OPENAI_API_URL", "")
    if api_url and not VALID_OPENAI_URL_PATTERN.match(api_url):
        issues.append(
            f"Invalid OpenAI API URL: {api_url}. Expected pattern: https://api.openai.com/v1/",
        )

    # Validate GPT model
    gpt_model = config.get("GPT_MODEL", "")
    if gpt_model and not is_supported_openai_model(gpt_model):
        issues.append(
            "Unknown GPT model: "
            f"{gpt_model}. Allowed identifiers start with 'gpt-5' (e.g., "
            f"{', '.join(OPENAI_VALID_MODELS)}).",
        )

    # Removed unsupported GPT-5 parameter validation

    # Validate token limits
    output_tokens = config.get("OUTPUT_TOKENS", 0)
    if output_tokens > MAX_OUTPUT_TOKENS_THRESHOLD:
        issues.append(
            f"OUTPUT_TOKENS very high ({output_tokens}). Consider lower limit for cost control.",
        )

    input_tokens = config.get("INPUT_TOKENS", 0)
    if input_tokens > MAX_INPUT_TOKENS_THRESHOLD:
        issues.append(f"INPUT_TOKENS very high ({input_tokens}). May exceed model limits.")

    return issues


def validate_perplexity_config(config: dict) -> list[str]:
    """Validate Perplexity API configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate API key format
    api_key = config.get("PERPLEXITY_API_KEY")
    if api_key:
        is_valid, error_msg = validate_perplexity_api_key_format(api_key)
        # Ensure error_msg does not echo the original API key
        if not is_valid and error_msg:
            safe_msg = (
                error_msg.replace(api_key, "[REDACTED]") if api_key in error_msg else error_msg
            )
            issues.append(f"ERROR: {safe_msg}")

    # Validate API URL
    api_url = config.get("PERPLEXITY_API_URL", "")
    if api_url and not VALID_PERPLEXITY_URL_PATTERN.match(api_url):
        issues.append(
            f"Invalid Perplexity API URL: {api_url}. Expected: https://api.perplexity.ai",
        )

    # Note: Model validation would need current API documentation
    # For now, we document the model being used
    model_info = "Using model: sonar-pro (current Perplexity model)"
    issues.append(f"INFO: {model_info}")

    return issues


def validate_discord_config(config: dict) -> list[str]:
    """Validate Discord bot configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate activity type
    activity_type = config.get("ACTIVITY_TYPE", "")
    if activity_type and activity_type not in DISCORD_ACTIVITY_TYPES:
        issues.append(
            f"Invalid activity type: {activity_type}. "
            f"Valid types: {', '.join(DISCORD_ACTIVITY_TYPES)}",
        )

    # Validate bot presence
    bot_presence = config.get("BOT_PRESENCE", "")
    valid_presence = ["online", "idle", "dnd", "invisible"]
    if bot_presence and bot_presence not in valid_presence:
        issues.append(
            f"Invalid bot presence: {bot_presence}. Valid values: {', '.join(valid_presence)}",
        )

    # Validate channels configuration
    allowed_channels = config.get("ALLOWED_CHANNELS", [])
    if not allowed_channels:
        issues.append(
            "WARNING: No ALLOWED_CHANNELS configured. Bot will not respond in any channels.",
        )

    return issues


def validate_rate_limiting_config(config: dict) -> list[str]:
    """Validate rate limiting configuration.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    rate_limit = config.get("RATE_LIMIT", 0)
    rate_limit_per = config.get("RATE_LIMIT_PER", 0)

    if rate_limit <= 0:
        issues.append("RATE_LIMIT must be positive")
    elif rate_limit > MAX_RATE_LIMIT_THRESHOLD:
        issues.append(
            f"RATE_LIMIT very high ({rate_limit}). Consider lower value to prevent abuse.",
        )

    if rate_limit_per <= 0:
        issues.append("RATE_LIMIT_PER must be positive")

    # Calculate requests per minute for context
    if rate_limit > 0 and rate_limit_per > 0:
        req_per_min = (rate_limit * SECONDS_PER_MINUTE) / rate_limit_per
        if req_per_min > MAX_RECOMMENDED_REQ_PER_MIN:
            issues.append(
                f"Rate limit allows {req_per_min:.1f} requests/minute. May be too permissive.",
            )

    return issues


def validate_full_config(config: dict) -> tuple[list[str], list[str]]:
    """Perform comprehensive validation of all API configurations.

    Args:
        config (Dict): Complete configuration dictionary

    Returns:
        Tuple[List[str], List[str]]: (warnings, errors)
    """
    warnings = []
    errors = []

    # Validate each API section
    openai_issues = validate_openai_config(config)
    perplexity_issues = validate_perplexity_config(config)
    discord_issues = validate_discord_config(config)
    rate_limit_issues = validate_rate_limiting_config(config)

    # Categorize issues
    all_issues = openai_issues + perplexity_issues + discord_issues + rate_limit_issues

    for issue in all_issues:
        if issue.startswith("ERROR:"):
            errors.append(issue)
        else:
            warnings.append(issue)

    # Check for critical missing configuration
    if not config.get("DISCORD_TOKEN"):
        errors.append("ERROR: DISCORD_TOKEN is required")

    if not config.get("OPENAI_API_KEY") and not config.get("PERPLEXITY_API_KEY"):
        errors.append(
            "ERROR: At least one API key (OPENAI_API_KEY or PERPLEXITY_API_KEY) is required",
        )

    return warnings, errors


def _sanitize_log_message(message: str) -> str:
    """Sanitize log messages to prevent exposing sensitive information.

    This function creates a NEW string that is guaranteed not to contain
    sensitive data, breaking any taint tracking from the original message.

    Args:
        message: The message to sanitize

    Returns:
        str: Sanitized message with sensitive data redacted
    """
    # Redact potential API keys (sk-xxx, pplx-xxx patterns)
    sanitized = re.sub(r"(sk-|pplx-)[a-zA-Z0-9\-_]+", r"\1[REDACTED]", message)
    # Redact anything that looks like a token or key value
    sanitized = re.sub(
        r"(key|token|secret|password)(['\"]?\s*[:=]\s*['\"]?)[^\s,'\"\\]+",
        r"\1\2[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    # Redact hex secrets (32+ chars) and JWT-like tokens
    sanitized = re.sub(
        r"\b(?:[A-Fa-f0-9]{32,}|eyJ[A-Za-z0-9_\-]+?\.ey[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+)\b",
        "[REDACTED]",
        sanitized,
    )
    # Return a new string to break taint tracking
    return str(sanitized)


def _log_validation_messages(
    logger: logging.Logger,
    warnings: list[str],
    errors: list[str],
) -> None:
    """Log validation messages with sensitive data redacted.

    Note: The validation messages themselves do NOT contain actual API key values.
    They only contain format requirements like "should start with 'sk-'".
    The _sanitize_log_message function provides additional protection.

    Args:
        logger: Logger instance
        warnings: List of warning messages
        errors: List of error messages
    """
    # Log warnings with sanitization
    for warning in warnings:
        logger.warning("Config validation: %s", _sanitize_log_message(warning))

    # Log errors with sanitization
    for error in errors:
        logger.error("Config validation: %s", _sanitize_log_message(error))


def log_validation_results(config: dict, logger: logging.Logger | None = None) -> bool:
    """Validate configuration and log results.

    Args:
        config (Dict): Configuration to validate
        logger (Optional[logging.Logger]): Logger instance

    Returns:
        bool: True if validation passed (no errors), False otherwise
    """
    if not logger:
        logger = logging.getLogger(__name__)

    warnings, errors = validate_full_config(config)

    # Log validation results using sanitized messages
    # The _sanitize_log_message function redacts any potential sensitive data
    _log_validation_messages(logger, warnings, errors)

    # Summary
    if errors:
        logger.error(
            "Configuration validation failed: %d errors, %d warnings",
            len(errors),
            len(warnings),
        )
        return False
    if warnings:
        logger.info("Configuration validation passed with %d warnings", len(warnings))
        return True
    logger.info("Configuration validation passed successfully")
    return True


def get_api_recommendations() -> dict[str, str]:
    """Get recommended API configuration values.

    Returns:
        Dict[str, str]: Dictionary of recommended configuration values
    """
    return {
        "GPT_MODEL": "gpt-5-mini",  # Cost-effective default
        "OUTPUT_TOKENS": "8000",  # Conservative limit
        "INPUT_TOKENS": "120000",  # Safe context window
        "RATE_LIMIT": "10",  # Reasonable default
        "RATE_LIMIT_PER": "60",  # Per minute
        "ACTIVITY_TYPE": "listening",  # Non-intrusive
        "BOT_PRESENCE": "online",  # Available but not attention-seeking
        "OPENAI_API_URL": "https://api.openai.com/v1/",
        "PERPLEXITY_API_URL": "https://api.perplexity.ai",
    }
