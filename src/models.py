"""Configuration models for AI services and requests."""

from dataclasses import dataclass, field
import logging
from typing import Any


@dataclass(frozen=True)
class AIRequest:
    """Groups common parameters for an AI request."""

    message: str
    user: Any
    conversation_manager: Any
    logger: logging.Logger


@dataclass(frozen=True)
class OpenAIConfig:
    """Configuration for OpenAI specific parameters."""

    model: str = "gpt-4-turbo"
    system_message: str = "You are a helpful assistant."
    output_tokens: int = 4000
    temperature: float = 0.7


@dataclass(frozen=True)
class PerplexityConfig:
    """Configuration for Perplexity specific parameters."""

    model: str = "sonar-pro"
    system_message: str = (
        "You are a helpful assistant with access to current web information. "
        "When providing citations, include source URLs when available."
    )
    output_tokens: int = 8000
    temperature: float = 0.7


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
