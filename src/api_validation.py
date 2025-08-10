"""API parameter validation for OpenAI, Perplexity, and Discord APIs.

This module provides functions to validate API parameters and configurations
against current API specifications to ensure compatibility and optimal performance.
"""

import logging
import re

# Valid API parameters and values
OPENAI_VALID_MODELS = [
    "gpt-5",  # Latest generation
    "gpt-4o",  # GPT-4 series - current
    "gpt-4o-mini",  # GPT-4 series - cost-effective
    "gpt-4",  # GPT-4 series - previous generation
    "gpt-4-turbo",  # GPT-4 series - enhanced
]

GPT5_REASONING_EFFORTS = ["minimal", "low", "medium", "high"]
GPT5_VERBOSITY_LEVELS = ["low", "medium", "high"]

DISCORD_ACTIVITY_TYPES = ["playing", "streaming", "listening", "watching", "custom", "competing"]

PERPLEXITY_MODELS = ["sonar-pro", "sonar"]  # Latest Perplexity model  # General Perplexity model

# API URL patterns
VALID_OPENAI_URL_PATTERN = re.compile(r"https://api\.openai\.com/v\d+/?")
VALID_PERPLEXITY_URL_PATTERN = re.compile(r"https://api\.perplexity\.ai/?")


def validate_openai_config(config: dict) -> list[str]:
    """Validate OpenAI API configuration parameters.

    Args:
        config (Dict): Configuration dictionary

    Returns:
        List[str]: List of validation warnings/errors
    """
    issues = []

    # Validate API URL
    api_url = config.get("OPENAI_API_URL", "")
    if api_url and not VALID_OPENAI_URL_PATTERN.match(api_url):
        issues.append(
            f"Invalid OpenAI API URL: {api_url}. Expected pattern: https://api.openai.com/v1/"
        )

    # Validate GPT model
    gpt_model = config.get("GPT_MODEL", "")
    if gpt_model and gpt_model not in OPENAI_VALID_MODELS:
        issues.append(
            f"Unknown GPT model: {gpt_model}. Known models: {', '.join(OPENAI_VALID_MODELS)}"
        )

    # Validate GPT-5 specific parameters
    reasoning_effort = config.get("REASONING_EFFORT")
    if reasoning_effort and reasoning_effort not in GPT5_REASONING_EFFORTS:
        issues.append(
            f"Invalid reasoning_effort: {reasoning_effort}. "
            f"Valid values: {', '.join(GPT5_REASONING_EFFORTS)}"
        )

    verbosity = config.get("VERBOSITY")
    if verbosity and verbosity not in GPT5_VERBOSITY_LEVELS:
        issues.append(
            f"Invalid verbosity: {verbosity}. Valid values: {', '.join(GPT5_VERBOSITY_LEVELS)}"
        )

    # Validate token limits
    output_tokens = config.get("OUTPUT_TOKENS", 0)
    if output_tokens > 50000:
        issues.append(
            f"OUTPUT_TOKENS very high ({output_tokens}). Consider lower limit for cost control."
        )

    input_tokens = config.get("INPUT_TOKENS", 0)
    if input_tokens > 200000:
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

    # Validate API URL
    api_url = config.get("PERPLEXITY_API_URL", "")
    if api_url and not VALID_PERPLEXITY_URL_PATTERN.match(api_url):
        issues.append(
            f"Invalid Perplexity API URL: {api_url}. Expected: https://api.perplexity.ai"
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
            f"Valid types: {', '.join(DISCORD_ACTIVITY_TYPES)}"
        )

    # Validate bot presence
    bot_presence = config.get("BOT_PRESENCE", "")
    valid_presence = ["online", "idle", "dnd", "invisible"]
    if bot_presence and bot_presence not in valid_presence:
        issues.append(
            f"Invalid bot presence: {bot_presence}. Valid values: {', '.join(valid_presence)}"
        )

    # Validate channels configuration
    allowed_channels = config.get("ALLOWED_CHANNELS", [])
    if not allowed_channels:
        issues.append(
            "WARNING: No ALLOWED_CHANNELS configured. Bot will not respond in any channels."
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
    elif rate_limit > 100:
        issues.append(
            f"RATE_LIMIT very high ({rate_limit}). Consider lower value to prevent abuse."
        )

    if rate_limit_per <= 0:
        issues.append("RATE_LIMIT_PER must be positive")

    # Calculate requests per minute for context
    if rate_limit > 0 and rate_limit_per > 0:
        req_per_min = (rate_limit * 60) / rate_limit_per
        if req_per_min > 60:
            issues.append(
                f"Rate limit allows {req_per_min:.1f} requests/minute. May be too permissive."
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
            "ERROR: At least one API key (OPENAI_API_KEY or PERPLEXITY_API_KEY) is required"
        )

    return warnings, errors


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

    # Log warnings
    for warning in warnings:
        logger.warning(f"Config validation: {warning}")

    # Log errors
    for error in errors:
        logger.error(f"Config validation: {error}")

    # Summary
    if errors:
        logger.error(
            f"Configuration validation failed: {len(errors)} errors, {len(warnings)} warnings"
        )
        return False
    if warnings:
        logger.info(f"Configuration validation passed with {len(warnings)} warnings")
        return True
    logger.info("Configuration validation passed successfully")
    return True


def get_api_recommendations() -> dict[str, str]:
    """Get recommended API configuration values.

    Returns:
        Dict[str, str]: Dictionary of recommended configuration values
    """
    return {
        "GPT_MODEL": "gpt-4o-mini",  # Cost-effective default
        "OUTPUT_TOKENS": "8000",  # Conservative limit
        "INPUT_TOKENS": "120000",  # Safe context window
        "RATE_LIMIT": "10",  # Reasonable default
        "RATE_LIMIT_PER": "60",  # Per minute
        "ACTIVITY_TYPE": "listening",  # Non-intrusive
        "BOT_PRESENCE": "online",  # Available but not attention-seeking
        "OPENAI_API_URL": "https://api.openai.com/v1/",
        "PERPLEXITY_API_URL": "https://api.perplexity.ai",
    }
