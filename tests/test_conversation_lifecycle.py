"""Conversation expiry and lookback semantics for the conversation manager."""

import configparser
from pathlib import Path
import re

from src.conversation_manager import ThreadSafeConversationManager

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    """Controllable monotonic-style clock for expiry tests."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _manager(clock: FakeClock, ttl: int = 60, **kwargs) -> ThreadSafeConversationManager:
    return ThreadSafeConversationManager(
        conversation_ttl_seconds=ttl,
        clock=clock,
        **kwargs,
    )


def test_idle_conversation_is_evicted_with_its_lock():
    clock = FakeClock()
    manager = _manager(clock, ttl=60)
    key = "g:1:c:1"

    manager.add_message(conversation_key=key, role="user", content="hello")
    manager.add_message(
        conversation_key=key,
        role="assistant",
        content="hi",
        metadata={"ai_service": "openai"},
    )

    assert manager.get_conversation(conversation_key=key)
    assert key in manager._user_locks

    clock.advance(61)

    assert manager.get_conversation(conversation_key=key) == []
    assert key not in manager._conversations
    assert key not in manager._user_locks
    assert key not in manager._last_activity


def test_conversation_touched_inside_ttl_survives():
    clock = FakeClock()
    manager = _manager(clock, ttl=60)
    key = "dm:42"

    manager.add_message(conversation_key=key, role="user", content="original")

    clock.advance(59)
    assert manager.get_conversation(conversation_key=key) == [
        {"role": "user", "content": "original"}
    ]

    clock.advance(2)
    assert manager.get_conversation(conversation_key=key) == [
        {"role": "user", "content": "original"}
    ]
    assert key in manager._conversations
    assert key in manager._user_locks


def test_zero_lookback_disables_service_lookup():
    manager = ThreadSafeConversationManager()
    key = "g:1:c:2"

    manager.add_message(conversation_key=key, role="user", content="first")
    manager.add_message(
        conversation_key=key,
        role="assistant",
        content="ancient perplexity answer",
        metadata={"ai_service": "perplexity"},
    )
    for index in range(5):
        manager.add_message(conversation_key=key, role="user", content=f"later {index}")

    assert manager.get_recent_ai_service(conversation_key=key, lookback_messages=0) is None


def test_negative_lookback_disables_service_lookup():
    manager = ThreadSafeConversationManager()
    key = "g:1:c:3"

    manager.add_message(conversation_key=key, role="user", content="first")
    manager.add_message(
        conversation_key=key,
        role="assistant",
        content="ancient perplexity answer",
        metadata={"ai_service": "perplexity"},
    )
    for index in range(5):
        manager.add_message(conversation_key=key, role="user", content=f"later {index}")

    assert manager.get_recent_ai_service(conversation_key=key, lookback_messages=-1) is None


def test_nonzero_lookback_only_sees_messages_inside_window():
    manager = ThreadSafeConversationManager()
    key = "g:1:c:4"

    manager.add_message(conversation_key=key, role="user", content="first")
    manager.add_message(
        conversation_key=key,
        role="assistant",
        content="perplexity answer",
        metadata={"ai_service": "perplexity"},
    )
    for index in range(4):
        manager.add_message(conversation_key=key, role="user", content=f"later {index}")

    assert manager.get_recent_ai_service(conversation_key=key, lookback_messages=5) == "perplexity"
    assert manager.get_recent_ai_service(conversation_key=key, lookback_messages=4) is None


def test_expiry_bounds_storage_after_many_distinct_conversations():
    clock = FakeClock()
    manager = _manager(clock, ttl=60)
    conversation_count = 10_000

    for index in range(conversation_count):
        manager.add_message(
            conversation_key=f"g:{index}:c:{index}",
            role="user",
            content=f"message {index}",
        )

    assert len(manager._conversations) == conversation_count
    assert len(manager._user_locks) == conversation_count

    clock.advance(61)
    manager.get_conversation(conversation_key="g:0:c:0")

    assert len(manager._conversations) == 0
    assert len(manager._user_locks) == 0
    assert len(manager._last_activity) == 0


def test_conversation_ttl_default_agrees_across_config_example_and_docs(monkeypatch):
    from src.config import DEFAULT_CONVERSATION_TTL_SECONDS, load_config

    monkeypatch.delenv("CONVERSATION_TTL_SECONDS", raising=False)

    loaded = load_config()
    assert loaded["CONVERSATION_TTL_SECONDS"] == 1800
    assert DEFAULT_CONVERSATION_TTL_SECONDS == 1800

    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "config.ini.example")
    assert parser.getint("Orchestrator", "CONVERSATION_TTL_SECONDS") == 1800

    docs = (REPO_ROOT / "docs" / "Configuration.md").read_text(encoding="utf-8")
    pattern = r"`CONVERSATION_TTL_SECONDS`[^\n]*?\(default:\s*`?1800`?\)"
    assert re.search(pattern, docs), "CONVERSATION_TTL_SECONDS default missing from docs"
