"""Shared construction of chat-completion message lists for AI providers."""

from math import ceil
from typing import Any

CHARS_PER_TOKEN = 4
TOKEN_ESTIMATE_MARGIN = 1.1
MESSAGE_OVERHEAD_TOKENS = 4
TRUNCATION_MARKER = "\n\n[truncated to fit the token budget]"
MINIMUM_PROMPT_TOKENS = 32


def _estimate_text_tokens(text: Any) -> int:
    """Estimate tokens for text using a conservative character ratio."""
    characters = len(str(text or ""))
    if characters == 0:
        return 0
    return ceil(characters * TOKEN_ESTIMATE_MARGIN / CHARS_PER_TOKEN)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate the tokens used by one chat message."""
    return MESSAGE_OVERHEAD_TOKENS + _estimate_text_tokens(message.get("content"))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate the tokens used by a complete message list."""
    return sum(estimate_message_tokens(message) for message in messages)


def resolve_completion_budget(
    output_tokens: int | None,
    context_window: int | None,
    input_tokens: int | None = None,
) -> int | None:
    """Return a completion budget that leaves a minimal prompt inside the window."""
    if output_tokens is None:
        return None

    completion_budget = max(0, int(output_tokens))
    if context_window is None:
        return completion_budget

    window = max(0, int(context_window))
    if window == 0:
        return completion_budget

    requested_prompt = max(0, int(input_tokens or 0))
    if max(requested_prompt, MINIMUM_PROMPT_TOKENS) + completion_budget <= window:
        return completion_budget

    return min(completion_budget, max(1, window - MINIMUM_PROMPT_TOKENS))


def resolve_prompt_budget(
    input_tokens: int | None,
    output_tokens: int | None,
    context_window: int | None,
    logger: Any = None,
) -> int | None:
    """Return the prompt budget after reserving room for the completion.

    The configured ``INPUT_TOKENS`` is used unless it plus the completion budget
    exceeds ``CONTEXT_WINDOW``. In that case the context window wins and the
    prompt budget is reduced, with a warning naming the conflicting settings.
    """
    if input_tokens is None:
        return None

    prompt_budget = max(0, int(input_tokens))
    if output_tokens is None or context_window is None:
        return prompt_budget

    window = max(0, int(context_window))
    if window == 0:
        return prompt_budget

    configured_output = max(0, int(output_tokens))
    completion_budget = resolve_completion_budget(output_tokens, context_window, input_tokens) or 0
    available_for_prompt = window - completion_budget
    if prompt_budget + configured_output > window:
        if logger is not None:
            logger.warning(
                "INPUT_TOKENS (%d) + OUTPUT_TOKENS (%d) exceed CONTEXT_WINDOW (%d); "
                "limiting prompt budget to %d tokens and completion budget to %d tokens",
                prompt_budget,
                configured_output,
                window,
                max(0, available_for_prompt),
                completion_budget,
            )
        prompt_budget = min(prompt_budget, max(0, available_for_prompt))
    return prompt_budget


def _history_units(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group history into whole question/answer pairs where possible."""
    units: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(history):
        message = history[index]
        following = history[index + 1] if index + 1 < len(history) else None
        if message.get("role") == "user" and following and following.get("role") == "assistant":
            units.append([message, following])
            index += 2
        else:
            units.append([message])
            index += 1
    return units


def _trim_history(
    system_message: dict[str, Any],
    user_message: dict[str, Any],
    history: list[dict[str, Any]],
    budget: int,
) -> list[dict[str, Any]]:
    """Drop the oldest history units until the prompt fits the budget."""
    units = _history_units(history)
    base_messages = [system_message, user_message]
    while units:
        kept = [message for unit in units for message in unit]
        messages = [system_message, *kept, user_message]
        if estimate_messages_tokens(messages) <= budget:
            break
        if len(units) == 1 and estimate_messages_tokens(base_messages) <= budget:
            break
        units.pop(0)
    return [message for unit in units for message in unit]


def _truncate_content_to_tokens(content: Any, max_message_tokens: int) -> str:
    """Shorten one message so its estimated tokens fit the given allowance."""
    text = str(content or "")
    text_budget = max_message_tokens - MESSAGE_OVERHEAD_TOKENS
    if text_budget <= 0:
        return ""

    marker_tokens = _estimate_text_tokens(TRUNCATION_MARKER)
    if text_budget <= marker_tokens:
        marker_chars = int(text_budget * CHARS_PER_TOKEN / TOKEN_ESTIMATE_MARGIN)
        return TRUNCATION_MARKER[: max(0, marker_chars)]

    available_chars = int((text_budget - marker_tokens) * CHARS_PER_TOKEN / TOKEN_ESTIMATE_MARGIN)
    available_chars = max(0, min(len(text), available_chars))
    while (
        available_chars > 0
        and _estimate_text_tokens(text[:available_chars] + TRUNCATION_MARKER) > text_budget
    ):
        available_chars -= 1

    prefix = text[:available_chars].rstrip()
    if not prefix:
        return TRUNCATION_MARKER
    return f"{prefix}{TRUNCATION_MARKER}"


def _fit_messages_to_budget(messages: list[dict[str, Any]], budget: int) -> None:
    """Truncate the largest messages until the list fits the budget."""
    estimates = [estimate_message_tokens(message) for message in messages]
    total = sum(estimates)
    minimum = MESSAGE_OVERHEAD_TOKENS + _estimate_text_tokens(TRUNCATION_MARKER)

    while total > budget:
        index = max(range(len(messages)), key=lambda position: estimates[position])
        if estimates[index] <= minimum:
            history_index = next((position for position in range(1, len(messages) - 1)), None)
            if history_index is None:
                break
            total -= estimates.pop(history_index)
            messages.pop(history_index)
            continue

        target = max(minimum, estimates[index] - (total - budget))
        if target >= estimates[index]:
            target = estimates[index] - 1

        content = _truncate_content_to_tokens(messages[index].get("content"), target)
        new_estimate = MESSAGE_OVERHEAD_TOKENS + _estimate_text_tokens(content)
        if new_estimate >= estimates[index]:
            break

        total += new_estimate - estimates[index]
        estimates[index] = new_estimate
        messages[index]["content"] = content


def build_messages(  # noqa: PLR0913
    system_message: str,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    context_window: int | None = None,
    logger: Any = None,
) -> list[dict[str, Any]]:
    """Build system, prior turns, and current user message in order.

    Args:
        system_message: The system prompt placed first.
        user_message: The current user message placed last.
        history: Optional prior conversation turns in chronological order.
        input_tokens: Optional prompt token budget.
        output_tokens: Optional completion token budget reserved inside the
            context window.
        context_window: Optional total model context window.
        logger: Optional logger for budget warnings and trim summaries.

    Returns:
        A message list containing the system message, any prior turns, and the
        current user message exactly once.
    """
    system_entry = {"role": "system", "content": system_message}
    current_entry = {"role": "user", "content": user_message}
    history_entries = [dict(message) for message in history] if history else []

    budget = resolve_prompt_budget(input_tokens, output_tokens, context_window, logger)
    if budget is None:
        return [system_entry, *history_entries, current_entry]

    before = estimate_messages_tokens([system_entry, *history_entries, current_entry])
    if before <= budget:
        return [system_entry, *history_entries, current_entry]

    trimmed_history = _trim_history(system_entry, current_entry, history_entries, budget)
    messages = [system_entry, *trimmed_history, current_entry]
    _fit_messages_to_budget(messages, budget)
    after = estimate_messages_tokens(messages)

    if logger is not None:
        kept_history = max(0, len(messages) - 2)
        logger.info(
            "Prompt token budget applied: estimated %d -> %d tokens "
            "(budget %d); trimmed %d history message(s)",
            before,
            after,
            budget,
            len(history_entries) - kept_history,
        )

    return messages
