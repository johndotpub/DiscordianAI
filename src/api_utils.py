"""API utilities for OpenAI, Perplexity, and other external services.

This module provides utility functions for building API parameters,
handling API responses, and managing API-specific logic in a clean,
reusable way.
"""

import logging
import re
from typing import Any


class OpenAIParams:
    """Builder class for OpenAI API parameters."""

    def __init__(self, model: str, max_tokens: int):
        """Initialize with model and max_tokens."""
        self.params = {
            "model": model,
            "max_tokens": max_tokens,
        }

    def add_messages(
        self, system_message: str, conversation_summary: list[dict], user_message: str
    ):
        """Add messages to the API call."""
        self.params["messages"] = [
            {"role": "system", "content": system_message},
            *conversation_summary,
            {"role": "user", "content": user_message},
        ]
        return self

    # Removed unsupported GPT-5 parameter helpers

    def build(self) -> dict[str, Any]:
        """Build the final parameters dictionary."""
        return self.params.copy()


class PerplexityParams:
    """Builder class for Perplexity API parameters."""

    def __init__(self, model: str | None = None, max_tokens: int = 8000):
        """Initialize with model (optional) and max_tokens."""
        self.params = {
            "model": model or "sonar-pro",  # Default fallback if not provided
            "max_tokens": max_tokens,
            "temperature": 0.7,  # Good for web search synthesis
        }

    def add_messages(self, system_message: str, user_message: str):
        """Add messages for Perplexity API."""
        self.params["messages"] = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        return self

    def set_temperature(self, temperature: float):
        """Set temperature for response creativity."""
        self.params["temperature"] = max(0.0, min(1.0, temperature))
        return self

    def build(self) -> dict[str, Any]:
        """Build the final parameters dictionary."""
        return self.params.copy()


def validate_gpt_model(model: str, logger: logging.Logger | None = None) -> bool:
    """Validate GPT model name against known models.

    Args:
        model: Model name to validate
        logger: Optional logger for warnings

    Returns:
        True if model is recognized
    """
    valid_models = {"gpt-5", "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-4-turbo"}

    is_valid = model in valid_models

    if not is_valid and logger:
        logger.warning(
            f"Unrecognized GPT model: {model}. Known models: {', '.join(sorted(valid_models))}"
        )

    return is_valid


def extract_api_error_info(exception: Exception) -> dict[str, Any]:
    """Extract structured information from API errors.

    Args:
        exception: API exception

    Returns:
        Dictionary with error information
    """
    error_msg = str(exception)

    info = {
        "error_type": type(exception).__name__,
        "message": error_msg,
        "is_rate_limit": "rate limit" in error_msg.lower() or "429" in error_msg,
        "is_timeout": "timeout" in error_msg.lower() or "timed out" in error_msg.lower(),
        "is_auth_error": "401" in error_msg or "unauthorized" in error_msg.lower(),
        "is_server_error": any(code in error_msg for code in ["500", "502", "503", "504"]),
        "retry_recommended": False,
        "retry_after": None,
    }

    # Determine if retry is recommended
    info["retry_recommended"] = (
        info["is_rate_limit"] or info["is_timeout"] or info["is_server_error"]
    )

    # Extract retry-after if present
    if info["is_rate_limit"]:
        retry_match = re.search(r"retry.*?(\d+)", error_msg.lower())
        if retry_match:
            info["retry_after"] = int(retry_match.group(1))

    return info


def log_api_call(
    logger: logging.Logger, service: str, model: str, message_length: int, conversation_length: int
):
    """Log API call information consistently.

    Args:
        logger: Logger instance
        service: Service name (e.g., "OpenAI", "Perplexity")
        model: Model name
        message_length: Length of user message
        conversation_length: Length of conversation history
    """
    logger.info(f"{service} API call - Model: {model}")
    logger.debug(
        f"Message length: {message_length} chars, History: {conversation_length} messages"
    )


def log_api_response(
    logger: logging.Logger,
    service: str,
    response_length: int,
    metadata: dict[str, Any] | None = None,
):
    """Log API response information consistently.

    Args:
        logger: Logger instance
        service: Service name
        response_length: Length of response
        metadata: Additional response metadata
    """
    logger.info(f"{service} response: {response_length} characters")

    if metadata:
        debug_parts = []
        if "finish_reason" in metadata:
            debug_parts.append(f"finish_reason: {metadata['finish_reason']}")
        if "usage" in metadata:
            usage = metadata["usage"]
            if hasattr(usage, "total_tokens"):
                debug_parts.append(f"tokens: {usage.total_tokens}")

        if debug_parts:
            logger.debug(" | ".join(debug_parts))


def build_system_message(base_message: str, context: dict[str, Any] | None = None) -> str:
    """Build system message with optional context.

    Args:
        base_message: Base system prompt
        context: Additional context to include

    Returns:
        Enhanced system message
    """
    if not context:
        return base_message

    additions = []

    if context.get("current_time"):
        additions.append(f"Current time: {context['current_time']}")

    if context.get("user_preferences"):
        prefs = context["user_preferences"]
        additions.append(f"User preferences: {prefs}")

    if context.get("conversation_context"):
        additions.append(f"Context: {context['conversation_context']}")

    if additions:
        return base_message + "\n\nAdditional context:\n" + "\n".join(additions)

    return base_message


def extract_usage_stats(response) -> dict[str, int]:
    """Extract usage statistics from API response.

    Args:
        response: API response object

    Returns:
        Dictionary with usage stats
    """
    stats = {}

    if hasattr(response, "usage"):
        usage = response.usage
        if hasattr(usage, "prompt_tokens"):
            stats["prompt_tokens"] = usage.prompt_tokens
        if hasattr(usage, "completion_tokens"):
            stats["completion_tokens"] = usage.completion_tokens
        if hasattr(usage, "total_tokens"):
            stats["total_tokens"] = usage.total_tokens

    return stats


def estimate_token_count(text: str) -> int:
    """Rough estimation of token count for text.

    This is a simple heuristic - for exact counts, use tiktoken.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Rough approximation: 1 token ≈ 4 characters
    # This varies by tokenizer but gives a reasonable estimate
    return len(text) // 4


def validate_token_limits(prompt_tokens: int, max_tokens: int, model_context_window: int) -> bool:
    """Validate that token usage fits within model limits.

    Args:
        prompt_tokens: Estimated prompt tokens
        max_tokens: Requested completion tokens
        model_context_window: Model's context window size

    Returns:
        True if within limits
    """
    total_needed = prompt_tokens + max_tokens
    return total_needed <= model_context_window


class APICallBuilder:
    """Helper class to build API calls consistently across services."""

    @staticmethod
    def openai_call(
        model: str,
        system_message: str,
        conversation_summary: list[dict],
        user_message: str,
        output_tokens: int,
    ) -> dict[str, Any]:
        """Build OpenAI API call parameters."""
        return (
            OpenAIParams(model, output_tokens)
            .add_messages(system_message, conversation_summary, user_message)
            .build()
        )

    @staticmethod
    def perplexity_call(
        system_message: str,
        user_message: str,
        model: str | None = None,
        max_tokens: int = 8000,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Build Perplexity API call parameters."""
        return (
            PerplexityParams(model, max_tokens)
            .add_messages(system_message, user_message)
            .set_temperature(temperature)
            .build()
        )


def safe_extract_response_content(response, _service: str = "API") -> str | None:
    """Safely extract content from API response without raising.

    Args:
        response: API response object
        _service: Unused service name (kept for backwards compatibility)

    Returns:
        Extracted content or None if unavailable
    """
    choices = getattr(response, "choices", None)
    if not choices or len(choices) == 0:
        return None

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", None)
    if content:
        return content.strip()
    return None
