"""Unified message handling for the Discord bot.

This module provides comprehensive message utilities, including:
- Intelligent message splitting for Discord limits
- Citation and embed formatting
- Content sanitization and cleaning
- User context and mention extraction
"""

import re
from typing import Any

import discord

from .config import (
    BARE_URL_PATTERN,
    EMBED_LIMIT,
    EMBED_SAFE_LIMIT,
    LINK_PATTERN,
    MAX_SPLIT_CHUNKS,
    MESSAGE_BUFFER,
    MESSAGE_LIMIT,
)
from .discord_embeds import citation_embed_formatter
from .truncation import truncate_with_notice

_RAW_MENTION_PATTERN = re.compile(r"<(@[!&]?|#)(\d+)>")
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+)\)")
_CONTINUED_FOOTER = "🌐 Web search results (continued)"

# ============================================================================
# CORE MESSAGE SENDING & SPLITTING
# ============================================================================


async def _deliver(
    channel: discord.TextChannel | discord.DMChannel,
    content: str,
    *,
    original_message: discord.Message | None = None,
    embed: discord.Embed | None = None,
    suppress_embeds: bool = False,
) -> None:
    """Reply to the invoking message or send to the channel under one policy."""
    kwargs: dict[str, Any] = {}
    if embed is not None:
        kwargs["embed"] = embed
    if embed is None or suppress_embeds:
        kwargs["suppress_embeds"] = suppress_embeds
    if original_message is not None:
        author = original_message.author
        mentioned_users = [] if getattr(author, "bot", False) is True else [author]
        kwargs["mention_author"] = False
        kwargs["allowed_mentions"] = discord.AllowedMentions(
            users=mentioned_users, replied_user=False
        )
        await original_message.reply(content, **kwargs)
    else:
        await channel.send(content, **kwargs)


def _truncate_to_limit(text: str, limit: int) -> str:
    """Truncate text to ``limit`` characters with the visible Discord notice."""
    notice = truncation_notice(len(text))
    available = limit - len(notice)
    if available <= 0:
        return text[:limit]
    truncated, _ = truncate_with_notice(text, available, notice)
    return truncated


def _split_message_chunks(
    message: str,
    first_limit: int,
    logger: Any,
    max_chunks: int = MAX_SPLIT_CHUNKS,
) -> list[str]:
    """Split a message into at most ``max_chunks`` pieces without recursion.

    Each piece except the first is bounded by ``MESSAGE_LIMIT``; the first is
    bounded by ``first_limit`` so a mention prefix still fits.  The existing
    natural-boundary and code-block-aware adjustments decide every split point.
    """
    chunks: list[str] = []
    remaining = message
    limit = first_limit

    while True:
        if len(remaining) <= limit:
            chunks.append(remaining)
            return chunks

        if len(chunks) >= max_chunks - 1:
            logger.error(
                "Message split reached chunk cap (%d) for message length %d",
                max_chunks,
                len(message),
            )
            chunks.append(_truncate_to_limit(remaining, limit))
            return chunks

        safe_target = max(1, limit - MESSAGE_BUFFER)
        safe_split_point = min(safe_target, len(remaining) - 1)
        split_index = find_optimal_split_point(remaining, safe_split_point)

        if split_index >= limit:
            split_index = max(1, limit - 1)

        before_split, after_split = adjust_split_for_code_blocks(remaining, split_index)

        if len(before_split) > limit:
            overflow = before_split[limit:]
            before_split = before_split[:limit]
            after_split = overflow + after_split

        if not before_split or len(after_split) >= len(remaining):
            if not chunks and limit < MESSAGE_LIMIT:
                # The mention prefix consumed the whole head.  Send that prefix-only
                # chunk, then retry the same text with a full-size chunk, matching
                # the old recursion's next step without recursing.
                chunks.append("")
                remaining = after_split or remaining
                limit = MESSAGE_LIMIT
                continue
            logger.warning(
                "Cannot split indivisible content of length %d within %d characters",
                len(remaining),
                limit,
            )
            chunks.append(_truncate_to_limit(remaining, limit))
            return chunks

        chunks.append(before_split)
        remaining = after_split
        limit = MESSAGE_LIMIT


# Preserve the existing positional API for current callers.
async def send_split_message(  # noqa: PLR0913, PLR0917
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    original_message: discord.Message | None = None,
    mention_prefix: str | None = None,
    _recursion_depth: int = 0,
    _chunk_budget: int | None = None,
) -> None:
    """Send messages with automatic splitting for Discord's message character limit.

    ``_recursion_depth`` is accepted for backwards compatibility and ignored:
    splitting is iterative and bounded by a chunk count instead.  ``_chunk_budget``
    lets an embed continuation share the same overall chunk cap.
    """
    logger = deps["logger"]
    message = sanitize_for_discord(message)
    prefix_text = mention_prefix or ""
    prefix_length = len(prefix_text)

    if prefix_length >= MESSAGE_LIMIT:
        logger.warning(
            "Mention prefix length %d exceeds Discord limit; omitting prefix",
            prefix_length,
        )
        prefix_text = ""
        prefix_length = 0
        mention_prefix = None

    max_first_chunk = max(1, MESSAGE_LIMIT - prefix_length)
    max_chunks = MAX_SPLIT_CHUNKS if _chunk_budget is None else _chunk_budget
    if max_chunks <= 0:
        logger.error("Message split chunk budget exhausted for length %d", len(message))
        return

    chunks = _split_message_chunks(message, max_first_chunk, logger, max_chunks)

    for index, chunk in enumerate(chunks):
        content = f"{prefix_text}{chunk}" if index == 0 and prefix_text else chunk
        if len(content) > MESSAGE_LIMIT:
            content, _ = truncate_with_notice(content, MESSAGE_LIMIT - 3, "...")
        await _deliver(
            channel,
            content,
            original_message=original_message,
            suppress_embeds=suppress_embeds,
        )


def _split_embed_head(message: str) -> tuple[str, str]:
    """Return the embed head and remaining text using the existing split rules."""
    if len(message) <= EMBED_SAFE_LIMIT:
        return message, ""
    split_index = find_optimal_split_point(message, EMBED_SAFE_LIMIT)
    return adjust_split_for_code_blocks(message, split_index)


def _rebuild_embed_head(
    embed: discord.Embed,
    head_text: str,
    citations: dict[str, str] | None,
) -> None:
    """Rebuild an embed description to match the adjusted head chunk."""
    head_citations = {c: u for c, u in (citations or {}).items() if f"[{c}]" in head_text}
    head_footer = embed.footer.text if embed.footer else None
    rebuilt_head, _ = citation_embed_formatter.create_citation_embed(
        head_text,
        head_citations,
        footer_text=head_footer,
    )
    embed.description = rebuilt_head.description
    # Preserve existing footer unless empty; otherwise copy rebuilt footer
    if (not embed.footer or not embed.footer.text) and rebuilt_head.footer:
        embed.set_footer(text=rebuilt_head.footer.text)


async def _send_embed_continuations(  # noqa: PLR0913, PLR0917
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    citations: dict[str, str],
    original_message: discord.Message | None,
    sent_messages: int,
) -> None:
    """Send the continuation embeds and text for an already-delivered head.

    This mirrors the former recursive call but counts chunks instead of depth.
    """
    logger = deps["logger"]
    remaining = message
    active_citations = citations

    while True:
        head_text, after_split = _split_embed_head(remaining)
        continuation_tail = after_split.strip()

        if sent_messages >= MAX_SPLIT_CHUNKS:
            logger.error(
                "Embed split reached chunk cap (%d) for message length %d",
                MAX_SPLIT_CHUNKS,
                len(message),
            )
            return
        if sent_messages >= MAX_SPLIT_CHUNKS - 1 and (
            continuation_tail or len(remaining) > EMBED_SAFE_LIMIT
        ):
            logger.error(
                "Embed split reached chunk cap (%d) for message length %d",
                MAX_SPLIT_CHUNKS,
                len(message),
            )
            await _deliver(
                channel,
                _truncate_to_limit(remaining, MESSAGE_LIMIT),
                original_message=original_message,
            )
            return

        cont_embed, _ = citation_embed_formatter.create_citation_embed(
            head_text,
            {c: u for c, u in active_citations.items() if f"[{c}]" in head_text},
            footer_text=_CONTINUED_FOOTER,
        )
        await _deliver(
            channel,
            "",
            original_message=original_message,
            embed=cont_embed,
        )
        sent_messages += 1

        if not continuation_tail:
            if active_citations and remaining and original_message:
                # Clean text fit the head but the embed was truncated; send the tail.
                await send_split_message(
                    channel,
                    remaining,
                    deps,
                    suppress_embeds=False,
                    original_message=original_message,
                    mention_prefix=None,
                    _chunk_budget=MAX_SPLIT_CHUNKS - sent_messages,
                )
            return

        message_part2 = continuation_tail
        remaining_citations = {
            c: u for c, u in active_citations.items() if f"[{c}]" in message_part2
        }
        if not remaining_citations:
            await send_split_message(
                channel,
                message_part2,
                deps,
                original_message=original_message,
                mention_prefix=None,
                _chunk_budget=MAX_SPLIT_CHUNKS - sent_messages,
            )
            return
        if len(message_part2) <= EMBED_LIMIT:
            if sent_messages >= MAX_SPLIT_CHUNKS:
                logger.error(
                    "Embed split reached chunk cap (%d) for message length %d",
                    MAX_SPLIT_CHUNKS,
                    len(message),
                )
                return
            final_embed, _ = citation_embed_formatter.create_citation_embed(
                message_part2,
                remaining_citations,
                footer_text=_CONTINUED_FOOTER,
            )
            await _deliver(
                channel,
                "",
                original_message=original_message,
                embed=final_embed,
            )
            return

        remaining = message_part2
        active_citations = remaining_citations


# Preserve the existing positional API for current callers.
async def send_split_message_with_embed(  # noqa: PLR0913, PLR0917
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    embed: discord.Embed,
    citations: dict[str, str] | None = None,
    original_message: discord.Message | None = None,
    mention_prefix: str | None = None,
    _recursion_depth: int = 0,
) -> None:
    """Send a long message with citation embeds, maintaining citations across parts.

    The provided embed is modified in place so the head chunk stays aligned with
    the adjusted text.  ``_recursion_depth`` is accepted for backwards
    compatibility and ignored; continuations are sent iteratively.
    """
    message = sanitize_for_discord(message)

    head_text, after_split = _split_embed_head(message)
    _rebuild_embed_head(embed, head_text, citations)
    await _deliver(
        channel,
        mention_prefix or "",
        original_message=original_message,
        embed=embed,
    )

    if after_split.strip():
        message_part2 = after_split.strip()
        remaining_citations = (
            {c: u for c, u in citations.items() if f"[{c}]" in message_part2} if citations else {}
        )
        if remaining_citations:
            if len(message_part2) > EMBED_LIMIT:
                await _send_embed_continuations(
                    channel,
                    message_part2,
                    deps,
                    remaining_citations,
                    original_message,
                    sent_messages=1,
                )
            else:
                cont_embed, _ = citation_embed_formatter.create_citation_embed(
                    message_part2,
                    remaining_citations,
                    footer_text=_CONTINUED_FOOTER,
                )
                await _deliver(
                    channel,
                    "",
                    original_message=original_message,
                    embed=cont_embed,
                )
        else:
            await send_split_message(
                channel,
                message_part2,
                deps,
                original_message=original_message,
                mention_prefix=None,
                _chunk_budget=MAX_SPLIT_CHUNKS - 1,
            )
    elif citations and message and original_message:
        # Embed was truncated but clean text fit; send remaining text to avoid dropping tail
        await send_split_message(
            channel,
            message,
            deps,
            suppress_embeds=False,
            original_message=original_message,
            mention_prefix=None,
            _chunk_budget=MAX_SPLIT_CHUNKS - 1,
        )


# Preserve the existing positional API for current callers.
async def send_formatted_message(  # noqa: PLR0913, PLR0917
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    embed_data: dict | None = None,
    original_message: discord.Message | None = None,
    mention_prefix: str | None = None,
) -> None:
    """Send formatted message to Discord, using extracted splitter logic."""
    logger = deps["logger"]
    message = sanitize_for_discord(message)

    if embed_data and "embed" in embed_data:
        embed = embed_data["embed"]
        clean_text = embed_data.get("clean_text", message)
        metadata = embed_data.get("embed_metadata") or embed_data.get("meta") or {}
        was_truncated = metadata.get("was_truncated", False)

        if was_truncated:
            citations = embed_data.get("citations", {})
            await send_split_message_with_embed(
                channel,
                clean_text,
                deps,
                embed,
                citations,
                original_message,
                mention_prefix,
            )
            return

        try:
            await _deliver(
                channel,
                mention_prefix or "",
                original_message=original_message,
                embed=embed,
            )
        except discord.HTTPException:
            logger.exception("Failed to send embed, falling back to split text")
            await send_split_message(
                channel,
                message,
                deps,
                suppress_embeds,
                original_message=original_message,
                mention_prefix=mention_prefix,
            )
    else:
        await send_split_message(
            channel,
            message,
            deps,
            suppress_embeds,
            original_message=original_message,
            mention_prefix=mention_prefix,
        )


# ============================================================================
# LOGICAL SPLITTING UTILITIES
# ============================================================================


def find_optimal_split_point(message: str, target_index: int) -> int:
    """Find the best place to split a message near a target index.

    Prioritizes splitting at natural boundaries like newlines,
    sentences, or word boundaries to maintain readability.
    """
    # Look for newlines within 100 characters of target
    search_start = max(0, target_index - 100)
    search_end = min(len(message), target_index + 100)
    search_area = message[search_start:search_end]

    # Find the last newline in the search area
    newline_pos = search_area.rfind("\n")
    if newline_pos != -1:
        return search_start + newline_pos + 1  # Split after the newline

    # No newline found, look for sentence boundaries
    sentence_endings = re.finditer(r"[.!?]\s+", search_area)
    sentence_positions = [match.end() for match in sentence_endings]

    if sentence_positions:
        # Choose the position closest to our target
        relative_target = target_index - search_start
        closest_sentence = min(sentence_positions, key=lambda pos: abs(pos - relative_target))
        return search_start + closest_sentence

    # Fall back to word boundary
    word_boundary = search_area.rfind(" ", 0, target_index - search_start)
    if word_boundary != -1:
        return search_start + word_boundary + 1

    # Last resort: use target index
    return target_index


def detect_code_blocks(text: str) -> list[tuple[int, int]]:
    """Detect code block boundaries in text."""
    pattern = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def is_inside_code_block(position: int, code_blocks: list[tuple[int, int]]) -> bool:
    """Check if a position is inside a code block."""
    return any(start <= position <= end for start, end in code_blocks)


def adjust_split_for_code_blocks(message: str, split_point: int) -> tuple[str, str]:
    """Adjust message split to avoid breaking code blocks."""
    code_blocks = detect_code_blocks(message)

    # If split point is not inside a code block, use it as-is
    if not is_inside_code_block(split_point, code_blocks):
        return message[:split_point], message[split_point:]

    # Find the code block containing our split point
    for start, end in code_blocks:
        if start <= split_point <= end:
            # If we're closer to the start, split before the code block
            if split_point - start < end - split_point:
                return message[:start], message[start:]
            # Otherwise, split after the code block
            return message[:end], message[end:]

    # Fallback (shouldn't reach here)
    return message[:split_point], message[split_point:]


# ============================================================================
# CONTENT CLEANING & LOGGING UTILITIES
# ============================================================================


def clean_message_content(content: str, max_length: int = 100) -> str:
    """Clean and truncate message content for logging."""
    if not content:
        return "[empty]"

    # Remove extra whitespace and newlines
    cleaned = re.sub(r"\s+", " ", content.strip())

    cleaned, _ = truncate_with_notice(cleaned, max_length, "...")

    return cleaned


def count_links(text: str) -> int:
    """Count the number of links in text for embed suppression decisions."""
    # Count Discord hyperlinks [title](url)
    discord_links = len(LINK_PATTERN.findall(text))

    # Count bare URLs
    bare_urls = len(BARE_URL_PATTERN.findall(text))

    return discord_links + bare_urls


def should_suppress_embeds(text: str, threshold: int = 2) -> bool:
    """Determine if embeds should be suppressed to reduce visual clutter."""
    return count_links(text) >= threshold


def sanitize_model_output(text: str, citations: dict[str, str] | None = None) -> str:
    """Neutralise mentions and non-citation markdown links in model output."""
    if not text:
        return ""

    allowed_urls = {str(url).strip() for url in (citations or {}).values() if str(url).strip()}

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if target in allowed_urls:
            return match.group(0)
        return label

    text = _MARKDOWN_LINK_PATTERN.sub(replace_link, text)
    text = _RAW_MENTION_PATTERN.sub(
        lambda match: f"<{match.group(1)}\u200b{match.group(2)}>",
        text,
    )
    return text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")


def sanitize_for_discord(text: str, citations: dict[str, str] | None = None) -> str:
    """Sanitize text for safe Discord sending."""
    return sanitize_model_output(text, citations)


def error_message(user_mention: str, error_text: str) -> str:
    """Format error message with user mention."""
    return f"{user_mention} {error_text}"


def truncation_notice(original_length: int) -> str:
    """Format message truncation notice."""
    return f"\n\n[Message truncated from {original_length} characters for Discord limits]"
