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

from __future__ import annotations

import warnings

__version__ = "0.2.8.0"
__author__ = "johndotpub"
__email__ = "github@john.pub"

# Discord.py still imports the legacy stdlib audioop module on initialization,
# which emits a DeprecationWarning under Python 3.12+. Ensure we filter that
# specific upstream warning before importing heavyweight modules so our global
# "-W error" test runs stay clean.
warnings.filterwarnings(
    "ignore",
    message="'audioop' is deprecated and slated for removal in Python 3.13",
    category=DeprecationWarning,
    module=r"discord\.player",
)

# Public API exports
try:
    from .bot import run_bot
    from .config import load_config, parse_arguments
except ImportError:  # pragma: no cover
    # Fallback for environments without discord or heavy dependencies
    run_bot = None
    load_config = None
    parse_arguments = None

__all__ = [
    "__author__",
    "__email__",
    "__version__",
    "load_config",
    "parse_arguments",
    "run_bot",
]
