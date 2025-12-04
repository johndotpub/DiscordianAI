"""DiscordianAI - A Discord bot powered by OpenAI and Perplexity AI.

This package provides a production-ready Discord bot with intelligent
AI service selection between OpenAI (GPT-5) for conversational tasks
and Perplexity for web search and factual queries.

Features:
    - Smart orchestration between OpenAI and Perplexity APIs
    - Thread-safe conversation management
    - Connection pooling for optimal API performance
    - Comprehensive error handling with circuit breakers
    - Rate limiting and graceful degradation

Example:
    >>> from src import load_config, run_bot
    >>> config = load_config("config.ini")
    >>> run_bot(config)
"""

__version__ = "0.2.8.0"
__author__ = "johndotpub"
__email__ = "github@john.pub"

# Public API exports
from .bot import run_bot
from .config import load_config, parse_arguments

__all__ = [
    "__author__",
    "__email__",
    "__version__",
    "load_config",
    "parse_arguments",
    "run_bot",
]
