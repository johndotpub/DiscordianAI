"""Tests for Discord context-aware logging adapters."""

import logging
from types import SimpleNamespace

from src.logging_adapter import ContextualLoggerAdapter, get_logger_with_context


def test_contextual_logger_adapter_process_with_guild_context():
    """process() should merge Discord guild context into extra."""
    adapter = ContextualLoggerAdapter(
        logging.getLogger("test"),
        {
            "guild_id": 123,
            "guild_name": "Guild Name",
            "channel_id": 456,
            "user_id": 789,
        },
    )

    msg, kwargs = adapter.process("hello", {})

    assert msg == "hello"
    assert kwargs["extra"]["guild_id"] == 123
    assert kwargs["extra"]["guild_name"] == "Guild Name"
    assert kwargs["extra"]["channel_id"] == 456
    assert kwargs["extra"]["user_id"] == 789


def test_contextual_logger_adapter_process_without_guild_context():
    """process() should not add guild fields for DMs."""
    adapter = ContextualLoggerAdapter(
        logging.getLogger("test"),
        {
            "channel_id": 456,
            "user_id": 789,
        },
    )

    _, kwargs = adapter.process("hello", {})

    assert kwargs["extra"]["channel_id"] == 456
    assert kwargs["extra"]["user_id"] == 789
    assert "guild_id" not in kwargs["extra"]
    assert "guild_name" not in kwargs["extra"]


def test_get_logger_with_context_returns_adapter():
    """get_logger_with_context() should return a ContextualLoggerAdapter."""
    message = SimpleNamespace(
        author=SimpleNamespace(id=111),
        channel=SimpleNamespace(id=222),
        guild=SimpleNamespace(id=333, name="Test Guild"),
    )

    adapter = get_logger_with_context(logging.getLogger("test"), message)

    assert isinstance(adapter, ContextualLoggerAdapter)
    assert adapter.extra["user_id"] == 111
    assert adapter.extra["channel_id"] == 222
    assert adapter.extra["guild_id"] == 333
    assert adapter.extra["guild_name"] == "Test Guild"
