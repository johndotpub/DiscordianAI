"""Pytest configuration helpers and shared fixtures for DiscordianAI tests."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock
import warnings

import pytest

# Discord.py still imports the stdlib audioop module, which raises a global
# DeprecationWarning on Python 3.12+ when tests enable ``-W error``. Keep the
# suite green by filtering that specific upstream warning while leaving the rest
# of the strict warning policy intact.
warnings.filterwarnings(
    "ignore",
    message="'audioop' is deprecated and slated for removal in Python 3.13",
    category=DeprecationWarning,
    module=r"discord\.player",
)


def _reset_provider_circuit_breakers() -> None:
    """Replace the shared provider breakers with fresh instances between tests."""
    import sys

    from src import error_handling

    registry = error_handling.PROVIDER_CIRCUIT_BREAKERS
    previous = dict(registry)
    replacements = {
        provider: error_handling.CircuitBreaker(name=provider) for provider in previous
    }
    registry.clear()
    registry.update(replacements)

    old_to_new = {id(breaker): replacements[provider] for provider, breaker in previous.items()}
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith("src."):
            continue
        for attribute, value in list(vars(module).items()):
            if id(value) in old_to_new:
                setattr(module, attribute, old_to_new[id(value)])


@pytest.fixture(autouse=True)
def reset_provider_circuit_breakers():
    """Keep provider breaker state isolated between tests."""
    _reset_provider_circuit_breakers()
    yield
    _reset_provider_circuit_breakers()


def _clear_response_cache_and_deduplicator() -> None:
    """Drop globally shared cache entries and in-flight dedup state."""
    from src.caching import request_deduplicator, response_cache

    response_cache.cache.clear()
    request_deduplicator._pending_requests.clear()


@pytest.fixture(autouse=True)
def reset_response_cache_and_deduplicator():
    """Prevent a cache hit in one test from masking a miss in the next."""
    _clear_response_cache_and_deduplicator()
    yield
    _clear_response_cache_and_deduplicator()


@pytest.fixture
def openai_response():
    """Return a factory for SDK-shaped OpenAI chat completion responses."""

    def _build(content="Test response from OpenAI", finish_reason="stop"):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = content
        response.choices[0].finish_reason = finish_reason
        response.id = "chatcmpl-test123"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 25
        response.usage.completion_tokens = 15
        response.usage.total_tokens = 40
        return response

    return _build


@pytest.fixture
def perplexity_response():
    """Return a factory for Perplexity responses carrying both citation fields."""

    def _build(content="Test response from Perplexity", citations=None, search_results=None):
        citations = list(citations or [])
        if search_results is None:
            search_results = [
                {
                    "title": f"Source {index}",
                    "url": url,
                    "date": "2026-10-27",
                    "last_updated": "2026-10-28",
                    "snippet": f"Snippet for source {index}",
                    "source": "web",
                }
                for index, url in enumerate(citations, 1)
            ]

        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = content
        response.choices[0].finish_reason = "stop"
        response.id = "pplx-test123"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 30
        response.usage.completion_tokens = 20
        response.usage.total_tokens = 50
        response.citations = citations
        response.search_results = search_results
        response.output = []
        if search_results:
            response.output.append({"type": "search_results", "results": search_results})
        response.output.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        )
        return response

    return _build


@pytest.fixture
def deps_factory():
    """Return a factory for a complete legacy-shaped deps dictionary."""

    def _build(**overrides):
        from src.dependencies import BotDependencies

        conversation_manager = MagicMock()
        conversation_manager.get_conversation_summary.return_value = []
        conversation_manager.get_conversation_summary_formatted.return_value = []

        dependencies = BotDependencies(
            bot=MagicMock(),
            logger=MagicMock(),
            config={},
            client=MagicMock(),
            perplexity_client=MagicMock(),
            rate_limiter=MagicMock(),
            conversation_manager=conversation_manager,
            circuit_breakers={},
            allowed_channels=["general"],
        )
        deps = dependencies.to_dict()
        deps.update(overrides)
        return deps

    return _build


@pytest.fixture
def config_dict():
    """Return a factory for config dictionaries seeded from production defaults."""

    def _build(**overrides):
        from src.config import _CONFIG_DEFAULTS

        config = deepcopy(_CONFIG_DEFAULTS)
        config.update(overrides)
        return config

    return _build


@pytest.fixture
def make_request():
    """Return a factory for AIRequest objects with sensible defaults."""

    def _build(message="Test message", user=None, key=None, **overrides):
        from src.models import AIRequest

        if user is None:
            user = MagicMock()
            user.id = 12345

        return AIRequest(
            message=message,
            user=user,
            conversation_manager=overrides.pop("conversation_manager", MagicMock()),
            logger=overrides.pop("logger", MagicMock()),
            conversation_key=key,
            **overrides,
        )

    return _build


@pytest.fixture
def mock_logger():
    """Return a MagicMock logger suitable for injection into deps."""
    return MagicMock()


@pytest.fixture
def mock_channel():
    """Return an AsyncMock Discord text channel with a mocked send method."""
    ch = AsyncMock()
    ch.send = AsyncMock()
    ch.id = 123456789
    ch.name = "general"
    return ch


@pytest.fixture
def mock_message():
    """Return an AsyncMock Discord message with a mocked reply method."""
    msg = AsyncMock()
    msg.reply = AsyncMock()
    msg.author.id = 987654321
    msg.author.name = "test_user"
    msg.author.mention = "<@987654321>"
    msg.content = "Hello, bot!"
    msg.channel.id = 123456789
    msg.channel.name = "general"
    return msg


@pytest.fixture
def mock_conversation_manager():
    """Return a MagicMock conversation manager with mocked add/get methods."""
    cm = MagicMock()
    cm.add_message = MagicMock()
    cm.get_conversation = MagicMock(return_value=[])
    cm.get_conversation_summary = MagicMock(return_value=[])
    return cm
