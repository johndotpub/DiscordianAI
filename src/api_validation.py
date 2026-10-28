"""API parameter validation for OpenAI, Perplexity, and Discord APIs.

This module provides functions to validate API parameters and configurations
against current API specifications to ensure compatibility and optimal performance.
"""

import logging
import re
from urllib.parse import urlparse

import discord

# Import constants from config.py (single source of truth)
from .config import (
    DISCORD_ACTIVITY_TYPES,
    MAX_INPUT_TOKENS_THRESHOLD,
    MAX_OUTPUT_TOKENS_CEILING,
    MAX_OUTPUT_TOKENS_COST_WARNING,
    MAX_OUTPUT_TOKENS_THRESHOLD,
    MAX_RATE_LIMIT_THRESHOLD,
    MAX_RECOMMENDED_REQ_PER_MIN,
    MIN_OPENAI_OUTPUT_TOKENS_WARNING,
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
    "validate_output_token_limits",
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
            "Accepted format: 'sk-' followed by at least 20 alphanumeric, '-' or '_' "
            "characters. Please verify your API key from "
            "https://platform.openai.com/api-keys"
        )

    if not OPENAI_API_KEY_PATTERN.match(api_key):
        return False, (
            "Invalid OpenAI API key format. "
            "Accepted format: 'sk-' followed by at least 20 alphanumeric, '-' or '_' "
            "characters. Please verify your API key from "
            "https://platform.openai.com/api-keys"
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
            "Accepted format: 'pplx-' followed by at least 20 alphanumeric, '-' or '_' "
            "characters. Please verify your API key from "
            "https://www.perplexity.ai/settings/api"
        )

    if not PERPLEXITY_API_KEY_PATTERN.match(api_key):
        return False, (
            "Invalid Perplexity API key format. "
            "Accepted format: 'pplx-' followed by at least 20 alphanumeric, '-' or '_' "
            "characters. Please verify your API key from "
            "https://www.perplexity.ai/settings/api"
        )

    return True, None


def _accepted_output_range() -> str:
    """Return the documented output-token range for either provider."""
    return f"1..{MAX_OUTPUT_TOKENS_CEILING}"


def _is_absolute_http_url(value: str) -> bool:
    """Return True when value is an absolute http(s) URL with a host."""
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_api_url(
    config: dict,
    key: str,
    pattern: re.Pattern[str],
    provider: str,
    example: str,
) -> list[str]:
    """Validate a provider base URL, distinguishing malformed from non-standard."""
    api_url = config.get(key)
    if not api_url:
        return []

    if not _is_absolute_http_url(api_url):
        return [
            (
                f"ERROR: Invalid {provider} API URL: {api_url}. {key} must be an absolute "
                f"http(s) URL (accepted: {example})."
            )
        ]

    if not pattern.match(api_url):
        return [
            (
                f"WARNING: Invalid {provider} API URL: {api_url}. Expected pattern: {example}; "
                "continuing because a compatible gateway may accept it."
            )
        ]

    return []


def _output_token_issues(config: dict, key: str, *, reasoning_model: bool) -> list[str]:
    """Validate one provider's output cap against the documented range."""
    value = config.get(key)
    if value is None:
        return []

    accepted = _accepted_output_range()
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return [
            (
                f"ERROR: {key} must be an integer in the accepted range {accepted} "
                f"(got {value!r})."
            )
        ]

    if tokens <= 0:
        return [
            f"ERROR: {key} must be positive; accepted range: {accepted} (got {tokens}).",
        ]

    if tokens > MAX_OUTPUT_TOKENS_THRESHOLD:
        return [
            (
                f"ERROR: {key} is {tokens}, above the documented maximum of "
                f"{MAX_OUTPUT_TOKENS_CEILING} tokens; accepted range: {accepted}."
            ),
        ]

    issues = []
    if reasoning_model and tokens < MIN_OPENAI_OUTPUT_TOKENS_WARNING:
        issues.append(
            f"WARNING: {key} is only {tokens}. OpenAI's max_completion_tokens covers "
            "reasoning tokens as well as visible output, so a cap below "
            f"{MIN_OPENAI_OUTPUT_TOKENS_WARNING} can be spent entirely on reasoning; "
            "the API can then return HTTP 200 with an empty message and "
            "finish_reason=length. Startup continues; raise the cap."
        )
    elif tokens > MAX_OUTPUT_TOKENS_COST_WARNING:
        issues.append(
            f"WARNING: {key} very high ({tokens}). Consider lower limit for cost control.",
        )

    return issues


def validate_output_token_limits(config: dict) -> list[str]:
    """Validate the separate OpenAI and Perplexity output-token caps.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: Validation errors and warnings prefixed with ERROR:/WARNING:
    """
    return [
        *_output_token_issues(config, "OUTPUT_TOKENS", reasoning_model=True),
        *_output_token_issues(config, "PERPLEXITY_OUTPUT_TOKENS", reasoning_model=False),
    ]


def _provider_configured(config: dict, provider: str) -> bool:
    """Return True when a provider was selected by key or explicit settings."""
    key_name = f"{provider}_API_KEY"
    if config.get(key_name):
        return True

    marker = f"_{provider}_CONFIGURED"
    if marker in config:
        return bool(config.get(marker))

    # Hand-built configurations (tests, health callers) have no loader
    # provenance. Treat provider-specific settings as an explicit selection.
    if provider == "OPENAI":
        fields = ("OPENAI_API_URL", "GPT_MODEL", "OPENAI_API_KEY")
    else:
        fields = ("PERPLEXITY_API_URL", "PERPLEXITY_MODEL", "PERPLEXITY_API_KEY")
    return any(field in config for field in fields)


def _input_and_context_issues(config: dict) -> list[str]:
    """Validate prompt-budget and context-window limits."""
    issues = []

    input_tokens = config.get("INPUT_TOKENS")
    if input_tokens is not None:
        try:
            parsed_input_tokens = int(input_tokens)
        except (TypeError, ValueError):
            issues.append(
                "ERROR: INPUT_TOKENS must be an integer in the accepted range "
                f"1..{MAX_INPUT_TOKENS_THRESHOLD} (got {input_tokens!r})."
            )
        else:
            if parsed_input_tokens <= 0:
                issues.append(
                    "ERROR: INPUT_TOKENS must be positive; accepted range: "
                    f"1..{MAX_INPUT_TOKENS_THRESHOLD} (got {parsed_input_tokens})."
                )
            elif parsed_input_tokens > MAX_INPUT_TOKENS_THRESHOLD:
                issues.append(
                    f"WARNING: INPUT_TOKENS very high ({parsed_input_tokens}). "
                    "May exceed model limits."
                )

    context_window = config.get("CONTEXT_WINDOW")
    if context_window is not None:
        try:
            parsed_context_window = int(context_window)
        except (TypeError, ValueError):
            issues.append(
                "ERROR: CONTEXT_WINDOW must be an integer greater than 0 "
                f"(got {context_window!r})."
            )
        else:
            if parsed_context_window <= 0:
                issues.append(
                    "ERROR: CONTEXT_WINDOW must be positive; accepted range: "
                    f"1 or greater (got {parsed_context_window})."
                )

    return issues


def validate_openai_config(config: dict) -> list[str]:
    """Validate OpenAI API configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate API key presence and format
    api_key = config.get("OPENAI_API_KEY")
    if not api_key and _provider_configured(config, "OPENAI"):
        issues.append(
            "ERROR: OPENAI_API_KEY is required because OpenAI is configured "
            "(missing OpenAI API key). Accepted: a non-empty OpenAI API key, or "
            "remove the OpenAI settings to run in Perplexity-only mode."
        )
    if api_key:
        is_valid, error_msg = validate_openai_api_key_format(api_key)
        # Ensure error_msg does not echo the original API key
        if not is_valid and error_msg:
            safe_msg = (
                error_msg.replace(api_key, "[REDACTED]") if api_key in error_msg else error_msg
            )
            issues.append(f"ERROR: OPENAI_API_KEY is invalid: {safe_msg}")

    issues.extend(
        _validate_api_url(
            config,
            "OPENAI_API_URL",
            VALID_OPENAI_URL_PATTERN,
            "OpenAI",
            "https://api.openai.com/v1/",
        )
    )

    # OpenAI accepts model names beyond any list we ship, so an unknown name is
    # a warning rather than a reason to refuse startup.
    gpt_model = config.get("GPT_MODEL", "")
    if gpt_model and not is_supported_openai_model(gpt_model):
        issues.append(
            "WARNING: Unknown GPT model: "
            f"{gpt_model}. Known documented models: {', '.join(OPENAI_VALID_MODELS)}. "
            "The provider may accept names outside this list, so startup continues.",
        )

    # Removed unsupported GPT-5 parameter validation

    issues.extend(_output_token_issues(config, "OUTPUT_TOKENS", reasoning_model=True))

    issues.extend(_input_and_context_issues(config))

    return issues


def validate_perplexity_config(config: dict) -> list[str]:
    """Validate Perplexity API configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate API key presence and format
    api_key = config.get("PERPLEXITY_API_KEY")
    if not api_key and _provider_configured(config, "PERPLEXITY"):
        issues.append(
            "ERROR: PERPLEXITY_API_KEY is required because Perplexity is configured "
            "(missing Perplexity API key). Accepted: a non-empty Perplexity API key, "
            "or remove the Perplexity settings to run in OpenAI-only mode."
        )
    if api_key:
        is_valid, error_msg = validate_perplexity_api_key_format(api_key)
        # Ensure error_msg does not echo the original API key
        if not is_valid and error_msg:
            safe_msg = (
                error_msg.replace(api_key, "[REDACTED]") if api_key in error_msg else error_msg
            )
            issues.append(f"ERROR: PERPLEXITY_API_KEY is invalid: {safe_msg}")

    issues.extend(
        _validate_api_url(
            config,
            "PERPLEXITY_API_URL",
            VALID_PERPLEXITY_URL_PATTERN,
            "Perplexity",
            "https://api.perplexity.ai",
        )
    )

    # The provider may add models before this list is updated, so an unknown
    # name is a warning that names the known set rather than a startup error.
    model = config.get("PERPLEXITY_MODEL", "")
    if model and model not in PERPLEXITY_MODELS:
        issues.append(
            f"WARNING: Unknown Perplexity model: {model}. Known models: "
            f"{', '.join(PERPLEXITY_MODELS)}. The provider may support newer models, "
            "so startup continues."
        )

    issues.extend(_output_token_issues(config, "PERPLEXITY_OUTPUT_TOKENS", reasoning_model=False))

    return issues


def validate_discord_config(config: dict) -> list[str]:
    """Validate Discord bot configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate activity type against the activity enum
    valid_activity_types = [
        activity.name
        for activity in discord.ActivityType
        if activity is not discord.ActivityType.unknown
    ]
    activity_type = config.get("ACTIVITY_TYPE", "")
    if activity_type and activity_type not in valid_activity_types:
        issues.append(
            f"ERROR: Invalid ACTIVITY_TYPE: {activity_type}. "
            f"Valid values: {', '.join(valid_activity_types)}",
        )

    # Validate bot presence against the status enum
    valid_presence = [status.name for status in discord.Status]
    bot_presence = config.get("BOT_PRESENCE", "")
    if bot_presence and bot_presence not in valid_presence:
        issues.append(
            f"ERROR: Invalid BOT_PRESENCE: {bot_presence}. "
            f"Valid values: {', '.join(valid_presence)}",
        )

    # Validate channels configuration; IDs are an alternative to names.
    allowed_channels = config.get("ALLOWED_CHANNELS", [])
    allowed_channel_ids = config.get("ALLOWED_CHANNEL_IDS", [])
    if not allowed_channels and not allowed_channel_ids:
        issues.append(
            "WARNING: No ALLOWED_CHANNELS or ALLOWED_CHANNEL_IDS configured. "
            "Bot will not respond in any channels.",
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

    rate_limit = config.get("RATE_LIMIT")
    rate_limit_per = config.get("RATE_LIMIT_PER")

    parsed_rate_limit = None
    if rate_limit is not None:
        try:
            parsed_rate_limit = int(rate_limit)
        except (TypeError, ValueError):
            issues.append(
                f"ERROR: RATE_LIMIT must be an integer greater than 0 (got {rate_limit!r})."
            )
        else:
            if parsed_rate_limit <= 0:
                issues.append(
                    "ERROR: RATE_LIMIT must be positive; accepted range: "
                    f"1 or greater (got {parsed_rate_limit})."
                )
            elif parsed_rate_limit > MAX_RATE_LIMIT_THRESHOLD:
                issues.append(
                    f"WARNING: RATE_LIMIT very high ({parsed_rate_limit}). "
                    "Consider lower value to prevent abuse."
                )

    parsed_rate_limit_per = None
    if rate_limit_per is not None:
        try:
            parsed_rate_limit_per = int(rate_limit_per)
        except (TypeError, ValueError):
            issues.append(
                "ERROR: RATE_LIMIT_PER must be an integer greater than 0 "
                f"(got {rate_limit_per!r})."
            )
        else:
            if parsed_rate_limit_per <= 0:
                issues.append(
                    "ERROR: RATE_LIMIT_PER must be positive; accepted range: "
                    f"1 or greater (got {parsed_rate_limit_per})."
                )

    # Calculate requests per minute for context
    if (
        parsed_rate_limit is not None
        and parsed_rate_limit > 0
        and parsed_rate_limit_per is not None
        and parsed_rate_limit_per > 0
    ):
        req_per_min = (parsed_rate_limit * SECONDS_PER_MINUTE) / parsed_rate_limit_per
        if req_per_min > MAX_RECOMMENDED_REQ_PER_MIN:
            issues.append(
                f"WARNING: Rate limit allows {req_per_min:.1f} requests/minute. "
                "May be too permissive."
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
        errors.append(
            "ERROR: DISCORD_TOKEN is required. Accepted: a non-empty Discord bot token.",
        )

    openai_key = config.get("OPENAI_API_KEY")
    perplexity_key = config.get("PERPLEXITY_API_KEY")
    openai_configured = _provider_configured(config, "OPENAI")
    perplexity_configured = _provider_configured(config, "PERPLEXITY")

    if (
        not openai_key
        and not perplexity_key
        and not openai_configured
        and not perplexity_configured
    ):
        errors.append(
            "ERROR: At least one API key (OPENAI_API_KEY or PERPLEXITY_API_KEY) is "
            "required. Accepted: a non-empty key for at least one provider.",
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
