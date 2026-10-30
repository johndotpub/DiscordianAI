"""Build a router input from an AI request and the conversation service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ConversationContext, RouterInput, Turn

_SERVICE_ROUTE: dict[str, str] = {"perplexity": "web", "openai": "local"}


def build_router_input(
    request: Any,
    conversation_manager: Any,
    lookback: int,
) -> RouterInput:
    """Return a pure ``RouterInput`` for ``request`` using only ``conversation_manager``.

    A missing manager, a missing conversation key, or a manager that raises
    produces an empty context. Routing must never fail because history could
    not be read.
    """
    text = _request_text(request)
    conversation_key = getattr(request, "conversation_key", None)
    if conversation_manager is None or conversation_key is None:
        return _input_for(request, text, ConversationContext())

    try:
        service = _recent_service(conversation_manager, conversation_key, lookback)
        history = _history(conversation_manager, conversation_key)
    except Exception:  # noqa: BLE001 - history is optional and caller-owned
        return _input_for(request, text, ConversationContext())

    turns = _turns(history, lookback)
    last_route = _service_route(service)
    if last_route is None:
        last_route = next(
            (turn.route for turn in reversed(turns) if turn.role == "assistant" and turn.route),
            None,
        )
    return _input_for(
        request,
        text,
        ConversationContext(turns=turns, last_route=last_route),
    )


def _request_text(request: Any) -> str:
    text = getattr(request, "message", None)
    if not isinstance(text, str):
        text = getattr(request, "text", "")
    return text if isinstance(text, str) else ""


def _recent_service(manager: Any, conversation_key: str, lookback: int) -> str | None:
    try:
        service = manager.get_recent_ai_service(
            conversation_key,
            lookback_messages=lookback,
        )
    except TypeError:
        service = manager.get_recent_ai_service(conversation_key, lookback)
    return service if isinstance(service, str) else None


def _history(manager: Any, conversation_key: str) -> Sequence[Mapping[str, Any]]:
    try:
        history = manager.get_conversation(conversation_key=conversation_key)
    except TypeError:
        history = manager.get_conversation(conversation_key)
    return history if isinstance(history, Sequence) else ()


def _turns(history: Sequence[Mapping[str, Any]], lookback: int) -> tuple[Turn, ...]:
    if lookback <= 0:
        return ()
    turns: list[Turn] = []
    for item in history[-lookback:]:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        metadata = item.get("metadata")
        route = None
        if isinstance(metadata, Mapping):
            route = _service_route(metadata.get("ai_service")) or metadata.get("route")
            if route not in {"web", "local"}:
                route = None
        turns.append(Turn(role=role, text=content, route=route))
    return tuple(turns)


def _service_route(service: object) -> str | None:
    if not isinstance(service, str):
        return None
    return _SERVICE_ROUTE.get(service.lower())


def _input_for(request: Any, text: str, context: ConversationContext) -> RouterInput:
    now = getattr(request, "now", None)
    if now is None:
        return RouterInput(text=text, context=context)
    return RouterInput(text=text, context=context, now=now)
