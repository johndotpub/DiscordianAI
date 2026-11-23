"""Shared construction of chat-completion message lists for AI providers."""

from collections.abc import Sequence
from math import ceil
from typing import Any

from .config import DEFAULT_VISION_TOKEN_ESTIMATE
from .image_attachments import ImagePayload

CHARS_PER_TOKEN = 4
TOKEN_ESTIMATE_MARGIN = 1.1
MESSAGE_OVERHEAD_TOKENS = 4
TRUNCATION_MARKER = "\n\n[truncated to fit the token budget]"
MINIMUM_PROMPT_TOKENS = 32


def estimate_text_tokens(text: Any) -> int:
    """Estimate tokens for text using a conservative character ratio."""
    characters = len(str(text or ""))
    if characters == 0:
        return 0
    return ceil(characters * TOKEN_ESTIMATE_MARGIN / CHARS_PER_TOKEN)


def _estimate_content_tokens(content: Any, vision_token_estimate: int) -> int:
    """Estimate tokens for text content or a multimodal content list."""
    if not isinstance(content, list):
        return estimate_text_tokens(content)

    total = 0
    image_tokens = max(0, int(vision_token_estimate))
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            total += estimate_text_tokens(part.get("text"))
        elif part.get("type") == "image_url":
            total += image_tokens
    return total


def estimate_message_tokens(
    message: dict[str, Any],
    *,
    vision_token_estimate: int = DEFAULT_VISION_TOKEN_ESTIMATE,
) -> int:
    """Estimate the tokens used by one chat message.

    Image parts use a flat per-image estimate; base64 payload length is never
    counted as text.
    """
    return MESSAGE_OVERHEAD_TOKENS + _estimate_content_tokens(
        message.get("content"), vision_token_estimate
    )


def estimate_messages_tokens(
    messages: list[dict[str, Any]],
    *,
    vision_token_estimate: int = DEFAULT_VISION_TOKEN_ESTIMATE,
) -> int:
    """Estimate the tokens used by a complete message list."""
    return sum(
        estimate_message_tokens(message, vision_token_estimate=vision_token_estimate)
        for message in messages
    )


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
    *,
    vision_token_estimate: int,
) -> list[dict[str, Any]]:
    """Drop the oldest history units until the prompt fits the budget."""
    units = _history_units(history)
    base_messages = [system_message, user_message]
    while units:
        kept = [message for unit in units for message in unit]
        messages = [system_message, *kept, user_message]
        if (
            estimate_messages_tokens(messages, vision_token_estimate=vision_token_estimate)
            <= budget
        ):
            break
        if len(units) == 1 and (
            estimate_messages_tokens(base_messages, vision_token_estimate=vision_token_estimate)
            <= budget
        ):
            break
        units.pop(0)
    return [message for unit in units for message in unit]


def _truncate_content_to_tokens(content: Any, max_message_tokens: int) -> str:
    """Shorten one message so its estimated tokens fit the given allowance."""
    text = str(content or "")
    text_budget = max_message_tokens - MESSAGE_OVERHEAD_TOKENS
    if text_budget <= 0:
        return ""

    marker_tokens = estimate_text_tokens(TRUNCATION_MARKER)
    if text_budget <= marker_tokens:
        marker_chars = int(text_budget * CHARS_PER_TOKEN / TOKEN_ESTIMATE_MARGIN)
        return TRUNCATION_MARKER[: max(0, marker_chars)]

    available_chars = int((text_budget - marker_tokens) * CHARS_PER_TOKEN / TOKEN_ESTIMATE_MARGIN)
    available_chars = max(0, min(len(text), available_chars))
    while (
        available_chars > 0
        and estimate_text_tokens(text[:available_chars] + TRUNCATION_MARKER) > text_budget
    ):
        available_chars -= 1

    prefix = text[:available_chars].rstrip()
    if not prefix:
        return TRUNCATION_MARKER
    return f"{prefix}{TRUNCATION_MARKER}"


def _fit_messages_to_budget(
    messages: list[dict[str, Any]],
    budget: int,
    *,
    vision_token_estimate: int,
) -> None:
    """Trim text content until the list fits the budget.

    Image parts are never truncated or removed here: their token cost is fixed
    and the base64 payload must survive. When only image-bearing messages are
    left, the prompt can stay over budget because the images are the request.
    """
    estimates = [
        estimate_message_tokens(message, vision_token_estimate=vision_token_estimate)
        for message in messages
    ]
    total = sum(estimates)
    minimum = MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(TRUNCATION_MARKER)

    while total > budget:
        truncatable = [
            position
            for position, message in enumerate(messages)
            if isinstance(message.get("content"), str)
        ]
        if not truncatable:
            history_index = next((position for position in range(1, len(messages) - 1)), None)
            if history_index is None:
                break
            total -= estimates.pop(history_index)
            messages.pop(history_index)
            continue

        index = max(truncatable, key=lambda position: estimates[position])
        if estimates[index] <= minimum:
            history_index = next(
                (
                    position
                    for position in range(1, len(messages) - 1)
                    if isinstance(messages[position].get("content"), str)
                ),
                None,
            )
            if history_index is None:
                break
            total -= estimates.pop(history_index)
            messages.pop(history_index)
            continue

        target = max(minimum, estimates[index] - (total - budget))
        if target >= estimates[index]:
            target = estimates[index] - 1

        content = _truncate_content_to_tokens(messages[index].get("content"), target)
        new_estimate = MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(content)
        if new_estimate >= estimates[index]:
            break

        total += new_estimate - estimates[index]
        estimates[index] = new_estimate
        messages[index]["content"] = content


def _multimodal_content(user_message: str, images: Sequence[ImagePayload]) -> list[dict[str, Any]]:
    """Return the OpenAI-compatible content list for a user turn with images."""
    content: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": f"data:{image.mime};base64,{image.data_b64}"},
        }
        for image in images
    )
    return content


def build_messages(  # noqa: PLR0913
    system_message: str,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    context_window: int | None = None,
    logger: Any = None,
    images: Sequence[ImagePayload] | None = None,
    vision_token_estimate: int = DEFAULT_VISION_TOKEN_ESTIMATE,
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
        images: Optional image payloads attached to the current turn. History
            turns stay text-only.
        vision_token_estimate: Flat prompt-token estimate charged per image.

    Returns:
        A message list containing the system message, any prior turns, and the
        current user message exactly once. The current message carries a
        multimodal content list when images are present.
    """
    system_entry = {"role": "system", "content": system_message}
    image_payloads = tuple(images or ())
    if image_payloads:
        current_entry = {
            "role": "user",
            "content": _multimodal_content(user_message, image_payloads),
        }
    else:
        current_entry = {"role": "user", "content": user_message}
    history_entries = [dict(message) for message in history] if history else []

    budget = resolve_prompt_budget(input_tokens, output_tokens, context_window, logger)
    if budget is None:
        return [system_entry, *history_entries, current_entry]

    before = estimate_messages_tokens(
        [system_entry, *history_entries, current_entry],
        vision_token_estimate=vision_token_estimate,
    )
    if before <= budget:
        return [system_entry, *history_entries, current_entry]

    trimmed_history = _trim_history(
        system_entry,
        current_entry,
        history_entries,
        budget,
        vision_token_estimate=vision_token_estimate,
    )
    messages = [system_entry, *trimmed_history, current_entry]
    _fit_messages_to_budget(
        messages,
        budget,
        vision_token_estimate=vision_token_estimate,
    )
    after = estimate_messages_tokens(messages, vision_token_estimate=vision_token_estimate)

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
