"""Shared construction of chat-completion message lists for AI providers."""

from typing import Any


def build_messages(
    system_message: str,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build system, prior turns, and current user message in order.

    Args:
        system_message: The system prompt placed first.
        user_message: The current user message placed last.
        history: Optional prior conversation turns in chronological order.

    Returns:
        A message list containing the system message, any prior turns, and the
        current user message exactly once.
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_message}]
    if history:
        messages.extend(dict(message) for message in history)
    messages.append({"role": "user", "content": user_message})
    return messages
