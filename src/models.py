"""Configuration models for AI services and requests."""

from dataclasses import dataclass, field
import logging
from typing import Any

from .config import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_INPUT_TOKENS,
    DEFAULT_MAX_TOTAL_SCRAPED_CHARS,
    DEFAULT_MAX_URLS_PER_MESSAGE,
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_PERPLEXITY_OUTPUT_TOKENS,
    DEFAULT_SCRAPE_DEADLINE_SECONDS,
)


@dataclass(frozen=True)
class AIRequest:
    """Groups common parameters for an AI request."""

    message: str
    user: Any
    conversation_manager: Any
    logger: logging.Logger
    conversation_key: str | None = None


@dataclass(frozen=True)
class OpenAIConfig:
    """Configuration for OpenAI specific parameters."""

    model: str = "gpt-5-mini"
    system_message: str = "You are a helpful assistant."
    output_tokens: int = DEFAULT_OUTPUT_TOKENS
    input_tokens: int = DEFAULT_INPUT_TOKENS
    context_window: int = DEFAULT_CONTEXT_WINDOW


@dataclass(frozen=True)
class PerplexityConfig:
    """Configuration for Perplexity specific parameters."""

    model: str = "sonar-pro"
    system_message: str = (
        "You are a helpful assistant with access to current web information. "
        "When providing citations, include source URLs when available."
    )
    output_tokens: int = DEFAULT_PERPLEXITY_OUTPUT_TOKENS
    max_urls_per_message: int = DEFAULT_MAX_URLS_PER_MESSAGE
    max_total_scraped_chars: int = DEFAULT_MAX_TOTAL_SCRAPED_CHARS
    scrape_deadline_seconds: float = DEFAULT_SCRAPE_DEADLINE_SECONDS
    input_tokens: int = DEFAULT_INPUT_TOKENS
    context_window: int = DEFAULT_CONTEXT_WINDOW


@dataclass(frozen=True)
class AIConfig:
    """Unified configuration for AI services."""

    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    perplexity: PerplexityConfig = field(default_factory=PerplexityConfig)


@dataclass(frozen=True)
class AIClients:
    """Group common AI clients for dependency injection."""

    openai: Any = None
    perplexity: Any = None
