"""The router input builder reads history only through the injected manager."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from src.routing.context import build_router_input

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
HISTORY_ERROR = "history backend down"


class _Manager:
    def __init__(
        self,
        *,
        service: str | None = "perplexity",
        history: list[dict[str, Any]] | None = None,
        raises: bool = False,
    ) -> None:
        self.service = service
        self.history = history or []
        self.raises = raises

    def get_recent_ai_service(self, conversation_key, lookback_messages=6):
        _ = (conversation_key, lookback_messages)
        if self.raises:
            raise RuntimeError(HISTORY_ERROR)
        return self.service

    def get_conversation(self, user_id=None, *, conversation_key=None):
        _ = (user_id, conversation_key)
        if self.raises:
            raise RuntimeError(HISTORY_ERROR)
        return list(self.history)


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        message="tell me more",
        conversation_key="g:1:c:2",
        now=FIXED_NOW,
    )


def test_missing_manager_or_key_returns_an_empty_context() -> None:
    """A helper must not require conversation history to build an input."""
    assert build_router_input(_request(), None, 6).context.turns == ()
    no_key = SimpleNamespace(message="hello", now=FIXED_NOW)
    assert build_router_input(no_key, _Manager(), 6).context.turns == ()


def test_manager_that_raises_returns_an_empty_context() -> None:
    """A broken history service degrades to empty context, never an exception."""
    result = build_router_input(_request(), _Manager(raises=True), 6)

    assert result.text == "tell me more"
    assert result.context.turns == ()
    assert result.context.last_route is None


def test_history_and_recent_service_become_turns_and_last_route() -> None:
    """Assistant service metadata maps back to the route it used."""
    manager = _Manager(
        service="perplexity",
        history=[
            {"role": "user", "content": "is github down"},
            {
                "role": "assistant",
                "content": "yes",
                "metadata": {"ai_service": "perplexity"},
            },
        ],
    )

    result = build_router_input(_request(), manager, 6)

    assert result.context.last_route == "web"
    assert [turn.route for turn in result.context.turns] == [None, "web"]
    assert result.context.turns[-1].role == "assistant"


class _StringHistoryManager(_Manager):
    def get_conversation(self, user_id=None, *, conversation_key=None):
        _ = (user_id, conversation_key)
        return "not a list of messages"


def test_string_history_returns_an_empty_context_without_raising() -> None:
    result = build_router_input(_request(), _StringHistoryManager(), 6)

    assert result.text == "tell me more"
    assert result.context.turns == ()
    assert result.context.last_route is None


def test_float_lookback_is_coerced_before_slicing_history() -> None:
    manager = _Manager(
        service=None,
        history=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
    )

    result = build_router_input(_request(), manager, 2.9)

    assert [turn.text for turn in result.context.turns] == ["second", "third"]
