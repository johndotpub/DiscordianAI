"""Pytest configuration helpers and shared fixtures for DiscordianAI tests."""

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
    """Reset the shared provider breakers in place between tests."""
    import asyncio

    from src.error_handling import PROVIDER_CIRCUIT_BREAKERS

    for breaker in PROVIDER_CIRCUIT_BREAKERS.values():
        breaker.failure_count = 0
        breaker.last_failure_time = 0.0
        breaker.last_success_time = 0.0
        breaker.state = "CLOSED"
        breaker._probe_in_flight = False
        breaker._lock = asyncio.Lock()


@pytest.fixture(autouse=True)
def reset_provider_circuit_breakers():
    """Keep provider breaker state isolated between tests."""
    _reset_provider_circuit_breakers()
    yield
    _reset_provider_circuit_breakers()


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
