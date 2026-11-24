"""Unified message handling for the Discord bot.

This module provides comprehensive message utilities, including:
- Intelligent message splitting for Discord limits
- Citation and embed formatting
- Content sanitization and cleaning
- User context and mention extraction
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import re
from typing import Any

import discord

from .citation_formatting import renderable_citations
from .config import (
    BARE_URL_PATTERN,
    CITATION_PATTERN,
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
_AUTOLINK_PATTERN = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)
_BARE_HTTP_URL_PATTERN = re.compile(r"https?://(?!\u200b)[^\s<>]+", re.IGNORECASE)
_FENCE_BLOCK_PATTERN = re.compile(r"(`{3,})[\s\S]*?\1")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}'\""
_CONTINUED_FOOTER = "🌐 Web search results (continued)"
TRUNCATION_NOTICE = "✂️ The answer was cut off at the length limit."

logger = logging.getLogger(__name__)


class CitationMap(dict[str, str]):
    """Citation mapping that records URLs parsed from the model's own text.

    Entries whose URL is in ``untrusted_urls`` may still appear as citation
    markers, but they must never be rendered as clickable links.
    """

    def __init__(
        self,
        *args: Any,
        untrusted_urls: Any = (),
        **kwargs: Any,
    ) -> None:
        """Build a citation map with an optional set of untrusted URLs."""
        super().__init__(*args, **kwargs)
        known = {str(url).strip() for url in self.values()}
        self.untrusted_urls = {
            str(url).strip() for url in (untrusted_urls or ()) if str(url).strip() in known
        }


def _citations_for_text(text: str, citations: dict[str, str] | None) -> CitationMap:
    """Return the citation entries whose markers occur in ``text``."""
    if not citations:
        return CitationMap()
    return CitationMap(
        ((number, url) for number, url in citations.items() if f"[{number}]" in text),
        untrusted_urls=getattr(citations, "untrusted_urls", ()),
    )


def _sanitize_embed_description(
    embed: discord.Embed,
    citations: dict[str, str] | None,
) -> None:
    """Sanitise an embed description in place when it is a real string."""
    description = getattr(embed, "description", None)
    if isinstance(description, str) and description:
        embed.description = sanitize_for_discord(description, citations)


# ============================================================================
# CORE MESSAGE SENDING & SPLITTING
# ============================================================================


async def _deliver(  # noqa: PLR0913 - one helper carries every delivery option
    channel: discord.TextChannel | discord.DMChannel,
    content: str,
    *,
    original_message: discord.Message | None = None,
    embed: discord.Embed | None = None,
    suppress_embeds: bool = False,
    mention_users: Sequence[Any] | None = None,
) -> None:
    """Send content under the one mention policy owned by this helper.

    A reply to ``original_message`` allows only that human author to be
    mentioned. A plain channel send with ``mention_users`` allows exactly the
    supplied users. Everyone, roles, and replied-user pings are always denied.

    The reply reference is built with ``fail_if_not_exists=False`` so Discord
    delivers the answer as a normal message when the question was deleted,
    instead of rejecting the request with an unknown-message error.
    """
    kwargs: dict[str, Any] = {}
    if embed is not None:
        kwargs["embed"] = embed
    if embed is None or suppress_embeds:
        kwargs["suppress_embeds"] = suppress_embeds
    mentioned_users: list[Any] = []
    if original_message is not None:
        author = original_message.author
        if getattr(author, "bot", False) is not True:
            mentioned_users = [author]
        kwargs["mention_author"] = False
        kwargs["reference"] = original_message.to_reference(fail_if_not_exists=False)
    elif mention_users is not None:
        mentioned_users = list(mention_users)
    kwargs["allowed_mentions"] = discord.AllowedMentions(
        users=mentioned_users,
        everyone=False,
        roles=[],
        replied_user=False,
    )
    await channel.send(content, **kwargs)


def append_truncation_notice(text: str) -> str:
    """Append the fixed length-limit notice to an answer exactly once."""
    if text.endswith(TRUNCATION_NOTICE):
        return text
    if not text:
        return TRUNCATION_NOTICE
    return f"{text.rstrip()}\n\n{TRUNCATION_NOTICE}"


def _truncate_to_limit(text: str, limit: int, original_length: int | None = None) -> str:
    """Truncate text to ``limit`` characters with the visible Discord notice."""
    notice = truncation_notice(len(text) if original_length is None else original_length)
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
            chunks.append(_truncate_to_limit(remaining, limit, len(message)))
            return chunks

        safe_target = max(1, limit - MESSAGE_BUFFER)
        safe_split_point = min(safe_target, len(remaining) - 1)
        split_index = find_optimal_split_point(remaining, safe_split_point)

        if split_index >= limit:
            split_index = max(1, limit - 1)

        before_split, after_split = split_fence_aware(remaining, limit, split_index)

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
            chunks.append(_truncate_to_limit(remaining, limit, len(message)))
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
    citations: dict[str, str] | None = None,
) -> None:
    """Send messages with automatic splitting for Discord's message character limit.

    ``_recursion_depth`` is accepted for backwards compatibility and ignored:
    splitting is iterative and bounded by a chunk count instead.  ``_chunk_budget``
    lets an embed continuation share the same overall chunk cap.  ``citations``
    is the allowlist of trusted citation URLs for link sanitisation.
    """
    logger = deps["logger"]
    message = sanitize_for_discord(message, citations)
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


def _rendered_embed_length(message: str, citations: dict[str, str] | None) -> int:
    """Return the embed description length after citation rendering."""
    if not citations:
        return len(message)
    return len(citation_embed_formatter.render_description(message, citations))


def _rendered_embed_split_point(message: str, citations: dict[str, str]) -> int:
    """Find the longest prefix whose rendered description fits the safe limit."""
    low = 0
    high = len(message)
    while low < high:
        middle = (low + high + 1) // 2
        if _rendered_embed_length(message[:middle], citations) <= EMBED_SAFE_LIMIT:
            low = middle
        else:
            high = middle - 1
    return low


def _split_embed_head(
    message: str,
    citations: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return the embed head and remaining text using the existing split rules.

    When citations are present the split is measured on the rendered embed
    description, because citation links expand the text beyond its clean length.
    """
    if not citations:
        if len(message) <= EMBED_SAFE_LIMIT:
            return message, ""
        split_index = find_optimal_split_point(message, EMBED_SAFE_LIMIT)
        split_index = _snap_citation_marker(message, split_index)
        return split_fence_aware(message, EMBED_SAFE_LIMIT, split_index)

    if _rendered_embed_length(message, citations) <= EMBED_SAFE_LIMIT:
        return message, ""

    max_prefix = _rendered_embed_split_point(message, citations)
    if max_prefix <= 0:
        split_index = min(len(message), EMBED_SAFE_LIMIT) or len(message)
        split_index = _snap_citation_marker(message, split_index)
        return split_fence_aware(message, max(1, split_index), split_index)

    split_index = min(max_prefix, find_optimal_split_point(message, max_prefix))
    if split_index <= 0:
        split_index = max_prefix
    split_index = _snap_citation_marker(message, split_index)
    if split_index <= 0:
        split_index = max_prefix
    return split_fence_aware(message, max_prefix, split_index)


def _rebuild_embed_head(
    embed: discord.Embed,
    head_text: str,
    citations: dict[str, str] | None,
) -> None:
    """Rebuild an embed description to match the adjusted head chunk."""
    head_citations = _citations_for_text(head_text, citations)
    head_footer = embed.footer.text if embed.footer else None
    rebuilt_head, _ = citation_embed_formatter.create_citation_embed(
        head_text,
        head_citations,
        footer_text=head_footer,
    )
    _sanitize_embed_description(rebuilt_head, citations)
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
    original_length: int | None = None,
) -> None:
    """Send the continuation embeds and text for an already-delivered head.

    This mirrors the former recursive call but counts chunks instead of depth.
    """
    logger = deps["logger"]
    remaining = message
    full_length = len(message) if original_length is None else original_length

    while True:
        head_text, after_split = _split_embed_head(remaining, citations)
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
                _truncate_to_limit(remaining, MESSAGE_LIMIT, full_length),
                original_message=original_message,
            )
            return

        head_citations = _citations_for_text(head_text, citations)
        cont_embed, _ = citation_embed_formatter.create_citation_embed(
            head_text,
            head_citations,
            footer_text=_CONTINUED_FOOTER,
        )
        _sanitize_embed_description(cont_embed, citations)
        await _deliver(
            channel,
            "",
            original_message=original_message,
            embed=cont_embed,
        )
        sent_messages += 1

        if not continuation_tail:
            return

        message_part2 = continuation_tail
        remaining_citations = _citations_for_text(message_part2, citations)
        if not remaining_citations:
            await send_split_message(
                channel,
                message_part2,
                deps,
                original_message=original_message,
                mention_prefix=None,
                _chunk_budget=MAX_SPLIT_CHUNKS - sent_messages,
                citations=citations,
            )
            return
        if _rendered_embed_length(message_part2, citations) <= EMBED_SAFE_LIMIT:
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
            _sanitize_embed_description(final_embed, citations)
            await _deliver(
                channel,
                "",
                original_message=original_message,
                embed=final_embed,
            )
            return

        remaining = message_part2


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
    message = sanitize_for_discord(message, citations)

    head_text, after_split = _split_embed_head(message, citations)
    _rebuild_embed_head(embed, head_text, citations)
    await _deliver(
        channel,
        mention_prefix or "",
        original_message=original_message,
        embed=embed,
    )

    if after_split.strip():
        message_part2 = after_split.strip()
        remaining_citations = _citations_for_text(message_part2, citations)
        if remaining_citations:
            if _rendered_embed_length(message_part2, citations) > EMBED_SAFE_LIMIT:
                await _send_embed_continuations(
                    channel,
                    message_part2,
                    deps,
                    citations,
                    original_message,
                    sent_messages=1,
                    original_length=len(message),
                )
            else:
                cont_embed, _ = citation_embed_formatter.create_citation_embed(
                    message_part2,
                    remaining_citations,
                    footer_text=_CONTINUED_FOOTER,
                )
                _sanitize_embed_description(cont_embed, citations)
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
                citations=citations,
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
    citations: dict[str, str] | None = None,
    truncated: bool = False,
) -> None:
    """Send formatted message to Discord, using extracted splitter logic.

    The citation allowlist is taken from ``citations`` or, when omitted, from
    ``embed_data["citations"]`` so trusted source links survive delivery.
    ``truncated`` appends the one fixed length-limit notice after the partial
    answer; the notice is delivery-only and never enters conversation history.
    """
    logger = deps["logger"]
    citation_map = citations
    if citation_map is None and embed_data:
        citation_map = embed_data.get("citations") or {}
    message = sanitize_for_discord(message, citation_map)
    if truncated:
        message = append_truncation_notice(message)

    if embed_data and "embed" in embed_data:
        embed = embed_data["embed"]
        clean_text = embed_data.get("clean_text", message)
        if truncated:
            if not clean_text:
                clean_text = getattr(embed, "description", "") or ""
            clean_text = append_truncation_notice(clean_text)
        metadata = embed_data.get("embed_metadata") or embed_data.get("meta") or {}
        was_truncated = metadata.get("was_truncated", False)

        if was_truncated or truncated:
            await send_split_message_with_embed(
                channel,
                clean_text,
                deps,
                embed,
                citation_map,
                original_message,
                mention_prefix,
            )
            return

        _sanitize_embed_description(embed, citation_map)
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
                citations=citation_map,
            )
    else:
        await send_split_message(
            channel,
            message,
            deps,
            suppress_embeds,
            original_message=original_message,
            mention_prefix=mention_prefix,
            citations=citation_map,
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


@dataclass(frozen=True)
class _FenceSpan:
    """One fenced code block, including its opening and closing lines."""

    start: int
    content_start: int
    end: int
    marker: str
    language: str


def _fence_span(text: str, start: int, marker: str, end: int, language: str) -> _FenceSpan:
    """Build a span and extend its end through the closing line's newline."""
    trailing = re.match(r"[ \t]*(?:\r\n|\n|\r)", text[end:])
    if trailing:
        end += trailing.end()
    content_start = text.find("\n", start + len(marker))
    if content_start == -1 or content_start >= end:
        content_start = min(start + len(marker), end)
    else:
        content_start += 1
    return _FenceSpan(
        start=start,
        content_start=content_start,
        end=end,
        marker=marker,
        language=language,
    )


def _fence_spans(text: str) -> list[_FenceSpan]:
    """Return fenced code blocks that Discord renders as code.

    Only a closed fence whose opening marker is not backslash-escaped counts.
    The splitter and the sanitiser share this detector, so a fence either
    protects link-like syntax or keeps a split inside the code block; an
    unclosed or escaped marker is literal text in both paths.
    """
    fences: list[_FenceSpan] = []
    for match in _FENCE_BLOCK_PATTERN.finditer(text):
        if _is_escaped(text, match.start()):
            continue
        marker = match.group(1)
        opening_end = match.start() + len(marker)
        newline = text.find("\n", opening_end, match.end())
        language = text[opening_end : newline if newline != -1 else match.end()].strip()
        fences.append(_fence_span(text, match.start(), marker, match.end(), language))
    return fences


def _snap_citation_marker(message: str, split_index: int) -> int:
    """Move a split index before a citation marker it would cut in half."""
    for match in CITATION_PATTERN.finditer(message):
        if match.start() < split_index < match.end():
            return match.start()
    return split_index


def split_fence_aware(
    message: str,
    limit: int,
    preferred: int | None = None,
) -> tuple[str, str]:
    """Split a message at a fence-safe boundary no later than ``limit``.

    When the preferred split falls inside a fenced code block, the split moves
    to before the block if it can, or to a line boundary inside it.  An inside
    split closes the fence at the end of the head and reopens it with the same
    marker and language tag at the start of the tail, so both halves render as
    code.  A single line wider than the available space is hard-wrapped rather
    than dropped.  The tail is always shorter than the input.

    Args:
        message: Text to split.
        limit: Maximum length of the returned head.
        preferred: Preferred raw split index; defaults to the natural boundary
            just before ``limit``.

    Returns:
        The head and tail; the concatenation of both contains every line of
        ``message`` plus any fence markers needed to keep the code balanced.
    """
    if len(message) <= limit:
        return message, ""

    if preferred is None:
        preferred = max(1, limit - MESSAGE_BUFFER)
    preferred = min(max(1, preferred), limit, len(message) - 1)

    fence = next(
        (span for span in _fence_spans(message) if span.start < preferred < span.end),
        None,
    )
    if fence is None:
        return message[:preferred], message[preferred:]

    if fence.end <= limit:
        return message[: fence.end], message[fence.end :]

    if fence.start > 0:
        return message[: fence.start], message[fence.start :]

    reopen = f"{fence.marker}{fence.language}\n"
    max_content = limit - len(fence.marker) - 1
    line_end = message.rfind("\n", fence.content_start, max_content + 1)

    if line_end >= fence.content_start:
        cut = line_end + 1
        head = f"{message[:cut]}{fence.marker}"
    else:
        cut = max(1, min(max_content, len(message) - 1))
        head_text = message[:cut]
        separator = "" if head_text.endswith("\n") else "\n"
        head = f"{head_text}{separator}{fence.marker}"

    return head, f"{reopen}{message[cut:]}"


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


def _normalize_link_target(target: str) -> str:
    """Strip whitespace and optional angle brackets from a link target."""
    target = target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return target


def _split_url_trailing_punctuation(url: str) -> tuple[str, str]:
    """Separate punctuation that Discord should not treat as part of a URL."""
    trailing = ""
    while url and url[-1] in _URL_TRAILING_PUNCTUATION:
        trailing = url[-1] + trailing
        url = url[:-1]
    return url, trailing


def _neutralize_url(url: str) -> str:
    """Make a URL non-clickable while keeping it readable.

    Discord autolinks bare ``http(s)://`` text. Inserting a zero-width space
    after the scheme terminator keeps the URL legible but stops Discord from
    recognising it as a link.
    """
    lower = url.lower()
    for scheme in ("https://", "http://"):
        if lower.startswith(scheme):
            return f"{url[: len(scheme)]}\u200b{url[len(scheme) :]}"
    return url


def _is_escaped(text: str, position: int) -> bool:
    """Return True when a backslash escapes the character at ``position``."""
    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _inline_code_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Return balanced inline code spans with unescaped backtick delimiters."""
    spans: list[tuple[int, int]] = []
    position = start

    while position < end:
        if text[position] != "`" or _is_escaped(text, position):
            position += 1
            continue

        run_start = position
        while position < end and text[position] == "`":
            position += 1
        run_length = position - run_start

        search = position
        while search < end:
            if text[search] != "`":
                search += 1
                continue
            close_start = search
            while search < end and text[search] == "`":
                search += 1
            if _is_escaped(text, close_start):
                continue
            if search - close_start == run_length:
                spans.append((run_start, search))
                position = search
                break

    return spans


def _rendered_code_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans Discord actually renders as code.

    Only closed fenced blocks and balanced, unescaped inline code spans count.
    An unclosed fence or a backslash-escaped backtick is literal text, so the
    links after it remain clickable and must be neutralised.
    """
    fences = [(span.start, span.end) for span in _fence_spans(text)]
    spans = list(fences)
    cursor = 0
    for fence_start, fence_end in fences:
        spans.extend(_inline_code_spans(text, cursor, fence_start))
        cursor = fence_end
    spans.extend(_inline_code_spans(text, cursor, len(text)))
    return sorted(spans)


def is_inside_rendered_code(text: str, position: int) -> bool:
    """Return True when ``position`` falls inside code Discord renders."""
    return any(start <= position < end for start, end in _rendered_code_spans(text))


def sanitize_model_output(text: str, citations: dict[str, str] | None = None) -> str:
    """Neutralise mentions and untrusted links in model output.

    Markdown links survive only when their target is a trusted, safely
    renderable citation URL. Bare ``http(s)://`` URLs and ``<...>`` autolinks
    are made non-clickable by inserting a zero-width space after the scheme
    terminator, which keeps the text readable without Discord autolinking it.
    A bare URL that exactly matches a trusted citation URL is left intact.

    The link rewrite runs over the whole text. Code that Discord renders is
    swapped for a placeholder first, then restored, so a link whose label is
    inline code is still evaluated. Only closed fenced blocks and balanced,
    unescaped inline code are protected: an unclosed fence or an escaped
    backtick is literal text and does not hide a link. Mention neutralisation
    applies everywhere, including inside code.

    Args:
        text: Model-generated text bound for Discord.
        citations: Optional citation map. Entries carrying an
            ``untrusted_urls`` set are treated as labels only.

    Returns:
        Text with mentions and untrusted links neutralised.
    """
    if not text:
        return ""

    allowed_urls = {
        str(url).strip() for url in renderable_citations(citations).values() if str(url).strip()
    }
    protected: list[str] = []

    def protect(rendered: str) -> str:
        token = f"\x00SAFE{len(protected)}\x00"
        protected.append(rendered)
        return token

    def protect_code(segment: str) -> str:
        spans = _rendered_code_spans(segment)
        if not spans:
            return segment
        parts: list[str] = []
        cursor = 0
        for start, end in spans:
            if start > cursor:
                parts.append(segment[cursor:start])
            parts.append(protect(segment[start:end]))
            cursor = end
        parts.append(segment[cursor:])
        return "".join(parts)

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        target = _normalize_link_target(match.group(2))
        if target in allowed_urls:
            return protect(match.group(0))
        return label

    def replace_autolink(match: re.Match[str]) -> str:
        target = _normalize_link_target(match.group(1))
        if target in allowed_urls:
            return protect(match.group(0))
        return _neutralize_url(match.group(1))

    def replace_bare_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        core, trailing = _split_url_trailing_punctuation(raw)
        if _normalize_link_target(core) in allowed_urls:
            return raw
        return f"{_neutralize_url(core)}{trailing}"

    text = protect_code(text)
    text = _MARKDOWN_LINK_PATTERN.sub(replace_link, text)
    text = _AUTOLINK_PATTERN.sub(replace_autolink, text)
    text = _BARE_HTTP_URL_PATTERN.sub(replace_bare_url, text)
    # Restore in reverse so a protected link can contain a protected code span.
    for index in range(len(protected) - 1, -1, -1):
        text = text.replace(f"\x00SAFE{index}\x00", protected[index])
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
    return (
        f"\n\n[Message truncated: the original answer was {original_length} characters; "
        "the bot's delivery limit was reached]"
    )
