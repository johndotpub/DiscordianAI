"""Unified message handling for the Discord bot.

This module provides comprehensive message utilities, including:
- Intelligent message splitting for Discord limits
- Citation and embed formatting
- Content sanitization and cleaning
- User context and mention extraction
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
import logging
import re
import threading
from typing import Any

import discord
from tree_sitter import Language, Parser, Range
import tree_sitter_markdown

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

_RAW_MENTION_PATTERN = re.compile(r"<(@[!&]?|#)(\d+)>")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}'\""
_CONTINUED_FOOTER = "🌐 Web search results (continued)"
TRUNCATION_NOTICE = "✂️ The answer was cut off at the length limit."
_ZERO_WIDTH_SPACE = "\u200b"
_FULL_BYTE_RANGE = Range((0, 0), (0xFFFFFFFF, 0xFFFFFFFF), 0, 0xFFFFFFFF)
_UTF8_ONE_BYTE_LIMIT = 0x80
_UTF8_TWO_BYTE_LIMIT = 0x800
_UTF8_THREE_BYTE_LIMIT = 0x10000
_FENCE_MARKER_LENGTH = 3
_CLOSING_DELIMITER_COUNT = 2

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


@dataclass(frozen=True)
class _FenceInfo:
    """One fenced block reported by the block grammar."""

    start: int
    end: int
    content_start: int
    marker: str
    language: str
    closed: bool


@dataclass(frozen=True)
class _InlineInfo:
    """One inline code span, link, image, or autolink reported by the parser."""

    start: int
    end: int
    kind: str
    destination: str = ""
    label_start: int = 0
    label_end: int = 0


@dataclass(frozen=True)
class _MarkdownParse:
    """Block and inline spans from one parse of a text."""

    text: str
    raw: bytes
    offsets: tuple[int, ...]
    fences: tuple[_FenceInfo, ...]
    inline: tuple[_InlineInfo, ...]


@dataclass(frozen=True)
class _CodeRegion:
    """A code region Discord renders, with enough detail to close a fence."""

    start: int
    end: int
    kind: str
    content_start: int = 0
    marker: str = "```"
    language: str = ""


@dataclass(frozen=True)
class _LinkSpan:
    """A parser-reported link or autolink that may need rewriting."""

    start: int
    end: int
    kind: str
    destination: str = ""
    label_start: int = 0
    label_end: int = 0
    allowed: bool = False


_thread_state = threading.local()


def _parsers() -> tuple[Parser, Parser]:
    """Return one block parser and one inline parser for this thread."""
    if not hasattr(_thread_state, "block_parser"):
        _thread_state.block_parser = Parser(Language(tree_sitter_markdown.language()))
        _thread_state.inline_parser = Parser(Language(tree_sitter_markdown.inline_language()))
    return _thread_state.block_parser, _thread_state.inline_parser


def _byte_offsets(raw: bytes, text: str) -> tuple[int, ...]:
    """Map every byte boundary in ``raw`` to a character index in ``text``."""
    offsets = [0] * (len(raw) + 1)
    byte_index = 0
    for character_index, character in enumerate(text):
        code_point = ord(character)
        if code_point < _UTF8_ONE_BYTE_LIMIT:
            size = 1
        elif code_point < _UTF8_TWO_BYTE_LIMIT:
            size = 2
        elif code_point < _UTF8_THREE_BYTE_LIMIT:
            size = 3
        else:
            size = 4
        for offset in range(size):
            offsets[byte_index + offset] = character_index
        byte_index += size
    offsets[len(raw)] = len(text)
    return tuple(offsets)


def _destination_text(text: str, offsets: tuple[int, ...], node: Any) -> str:
    """Return a link destination with optional angle brackets removed."""
    destination = text[offsets[node.start_byte] : offsets[node.end_byte]].strip()
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1].strip()
    return destination


def _inline_link_info(
    text: str,
    offsets: tuple[int, ...],
    node: Any,
) -> _InlineInfo | None:
    """Build an inline link or image span from one parser node."""
    destination_node = None
    label_node = None
    for child in node.children:
        if child.type in {"link_destination", "uri_autolink"} and destination_node is None:
            destination_node = child
        elif child.type in {"link_text", "image_description"} and label_node is None:
            label_node = child
    if destination_node is None:
        return None
    start = offsets[node.start_byte]
    end = offsets[node.end_byte]
    if label_node is None:
        label_start = label_end = start + 1
    else:
        label_start = offsets[label_node.start_byte]
        label_end = offsets[label_node.end_byte]
    return _InlineInfo(
        start=start,
        end=end,
        kind=node.type,
        destination=_destination_text(text, offsets, destination_node),
        label_start=label_start,
        label_end=label_end,
    )


def _fence_info_from_node(
    node: Any,
    raw: bytes,
    text: str,
    offsets: tuple[int, ...],
) -> _FenceInfo:
    """Build one fenced-block span from a block-grammar node."""
    delimiters = [child for child in node.children if child.type == "fenced_code_block_delimiter"]
    info = next((child for child in node.children if child.type == "info_string"), None)
    marker = ""
    if delimiters:
        marker = raw[delimiters[0].start_byte : delimiters[0].end_byte].decode("utf-8")
    closed = False
    if len(delimiters) >= _CLOSING_DELIMITER_COUNT:
        closing = raw[delimiters[-1].start_byte : delimiters[-1].end_byte].decode("utf-8")
        closed = closing == marker
    content_start = offsets[delimiters[0].end_byte] if delimiters else offsets[node.start_byte]
    newline = text.find("\n", content_start)
    node_end = offsets[node.end_byte]
    if newline != -1 and newline < node_end:
        content_start = newline + 1
    language = ""
    if info is not None:
        language = text[offsets[info.start_byte] : offsets[info.end_byte]].strip()
    return _FenceInfo(
        start=offsets[node.start_byte],
        end=node_end,
        content_start=content_start,
        marker=marker,
        language=language,
        closed=closed,
    )


def _inline_infos_from_node(
    node: Any,
    raw: bytes,
    text: str,
    offsets: tuple[int, ...],
    inline_parser: Parser,
) -> list[_InlineInfo]:
    """Reparse one inline node and return its code, link, and autolink spans."""
    inline_parser.included_ranges = [
        Range(node.start_point, node.end_point, node.start_byte, node.end_byte)
    ]
    spans: list[_InlineInfo] = []
    try:
        inline_tree = inline_parser.parse(raw)
        inline_stack = [inline_tree.root_node]
        while inline_stack:
            child = inline_stack.pop()
            if child.type == "code_span":
                spans.append(
                    _InlineInfo(
                        start=offsets[child.start_byte],
                        end=offsets[child.end_byte],
                        kind="code",
                    )
                )
            elif child.type in {"inline_link", "image"}:
                info_span = _inline_link_info(text, offsets, child)
                if info_span is not None:
                    spans.append(info_span)
            elif child.type in {"uri_autolink", "email_autolink"}:
                spans.append(
                    _InlineInfo(
                        start=offsets[child.start_byte],
                        end=offsets[child.end_byte],
                        kind=child.type,
                        destination=_destination_text(text, offsets, child),
                    )
                )
            inline_stack.extend(reversed(child.children))
    finally:
        inline_parser.included_ranges = [_FULL_BYTE_RANGE]
    return spans


def _parse_markdown(text: str, *, include_inline: bool = True) -> _MarkdownParse:
    """Parse one text with the block grammar and, unless disabled, inline spans."""
    raw = text.encode("utf-8")
    offsets = _byte_offsets(raw, text)
    block_parser, inline_parser = _parsers()
    tree = block_parser.parse(raw)
    fences: list[_FenceInfo] = []
    inline: list[_InlineInfo] = []
    stack = [tree.root_node]

    while stack:
        node = stack.pop()
        if node.type == "fenced_code_block":
            fences.append(_fence_info_from_node(node, raw, text, offsets))
        elif include_inline and node.type == "inline":
            inline.extend(_inline_infos_from_node(node, raw, text, offsets, inline_parser))
        stack.extend(reversed(node.children))

    return _MarkdownParse(
        text=text,
        raw=raw,
        offsets=offsets,
        fences=tuple(sorted(fences, key=lambda fence: fence.start)),
        inline=tuple(sorted(inline, key=lambda span: span.start)),
    )


def _backtick_run_lengths(text: str) -> set[int]:
    """Return the distinct backtick run lengths present in ``text``."""
    lengths: set[int] = set()
    position = 0
    while position < len(text):
        if text[position] != "`":
            position += 1
            continue
        start = position
        while position < len(text) and text[position] == "`":
            position += 1
        lengths.add(position - start)
    return lengths


def _filtered_code_regions(parse: _MarkdownParse) -> list[_CodeRegion]:
    """Return the code regions the conservative protection rule accepts.

    A fenced block is protected only when it uses exactly three backticks,
    is closed by a three-backtick closer, and no other triple-backtick run
    appears outside the accepted blocks. Any other shape makes the pairing
    uncertain, so the whole text protects nothing. Indented blocks are never
    protected because Discord has no indented code. Inline spans are skipped
    when the text mixes backtick run lengths, because the pairing is then
    ambiguous.
    """
    accepted = [fence for fence in parse.fences if fence.marker == "```" and fence.closed]
    accepted.sort(key=lambda fence: fence.start)

    accepted_index = 0
    run_index = parse.text.find("```")
    while run_index >= 0:
        while accepted_index < len(accepted) and accepted[accepted_index].end <= run_index:
            accepted_index += 1
        inside = (
            accepted_index < len(accepted)
            and accepted[accepted_index].start <= run_index < accepted[accepted_index].end
        )
        if not inside:
            return []
        run_index = parse.text.find("```", run_index + 3)

    regions = [
        _CodeRegion(
            start=fence.start,
            end=fence.end,
            kind="fence",
            content_start=fence.content_start,
            marker=fence.marker,
            language=fence.language,
        )
        for fence in accepted
    ]
    run_lengths = _backtick_run_lengths(parse.text)
    if len(run_lengths) <= 1:
        for span in parse.inline:
            if span.kind != "code":
                continue
            if _is_escaped(parse.text, span.start):
                continue
            regions.append(_CodeRegion(start=span.start, end=span.end, kind="inline"))
    regions.sort(key=lambda region: region.start)
    return regions


def protected_code_regions(text: str) -> list[_CodeRegion]:
    """Return the code regions that Discord renders for ``text``.

    The tree-sitter-markdown grammars supply the spans, but only a conservative
    subset is protected: an exactly-three-backtick closed fence with no other
    triple-backtick run outside it, or a closed inline code span whose opener
    is not backslash-escaped when the text uses one backtick run length. A
    block that fails any condition protects nothing, so protection can only
    ever be smaller than the parser reports.

    Args:
        text: Text that will be delivered to Discord.

    Returns:
        Sorted code regions, with byte offsets converted to character indices.
    """
    if not text:
        return []
    return _filtered_code_regions(_parse_markdown(text))


def _link_spans(parse: _MarkdownParse, allowed_urls: set[str]) -> list[_LinkSpan]:
    """Return parser-reported links and autolinks that sanitising may rewrite."""
    spans: list[_LinkSpan] = []
    for span in parse.inline:
        if span.kind == "uri_autolink":
            destination = span.destination
            spans.append(
                _LinkSpan(
                    start=span.start,
                    end=span.end,
                    kind="uri_autolink",
                    destination=destination,
                    allowed=destination in allowed_urls,
                )
            )
        elif span.kind == "email_autolink":
            spans.append(
                _LinkSpan(
                    start=span.start,
                    end=span.end,
                    kind="email_autolink",
                    destination=span.destination,
                )
            )
        elif span.kind in {"inline_link", "image"}:
            spans.append(
                _LinkSpan(
                    start=span.start,
                    end=span.end,
                    kind=span.kind,
                    destination=span.destination,
                    label_start=span.label_start,
                    label_end=span.label_end,
                    allowed=span.destination in allowed_urls,
                )
            )
    return spans


def _allowed_bare_url_spans(text: str, allowed_urls: set[str]) -> list[_LinkSpan]:
    """Return occurrences of an exact trusted URL so the catch-all skips them."""
    if not allowed_urls:
        return []
    spans: list[_LinkSpan] = []
    lower = text.lower()
    position = 0
    while True:
        http = lower.find("http://", position)
        https = lower.find("https://", position)
        candidates = [index for index in (http, https) if index >= 0]
        if not candidates:
            return spans
        start = min(candidates)
        end = start
        while end < len(text) and not text[end].isspace() and text[end] not in "<>":
            end += 1
        core, _trailing = _split_url_trailing_punctuation(text[start:end])
        core_end = start + len(core)
        if core in allowed_urls and text.startswith(core, start):
            after = text[core_end : core_end + 1]
            if not after or not (after.isalnum() or after in "-._~:/?#[]@!$&'()*+,;=%"):
                spans.append(_LinkSpan(start=start, end=core_end, kind="bare"))
        position = end


def _allowed_markdown_link_spans(text: str, allowed_urls: set[str]) -> list[_LinkSpan]:
    """Return trusted link spans the CommonMark parser may not accept.

    Discord embed citation links use a doubled bracket (``[[1]](url)``).
    CommonMark treats the inner brackets as a nested link and does not report
    the outer span, so the allowlist is checked directly for an exact
    destination. Only the closing bracket and destination are exempt; the
    label before it is still scanned by the catch-all passes.
    """
    if not allowed_urls:
        return []
    spans: list[_LinkSpan] = []
    position = 0
    while True:
        marker = text.find("](", position)
        if marker < 0:
            return spans
        destination_start = marker + 2
        while destination_start < len(text) and text[destination_start] in " \t":
            destination_start += 1
        if destination_start < len(text) and text[destination_start] == "<":
            destination_end = text.find(">", destination_start + 1)
            if destination_end < 0:
                position = marker + 2
                continue
            destination = text[destination_start + 1 : destination_end]
            close_start = destination_end + 1
        else:
            destination_end = destination_start
            while (
                destination_end < len(text)
                and not text[destination_end].isspace()
                and text[destination_end] not in ")]"
            ):
                destination_end += 1
            destination = text[destination_start:destination_end]
            close_start = destination_end
        closing = text.find(")", close_start)
        if destination in allowed_urls and closing >= 0:
            spans.append(_LinkSpan(start=marker, end=closing + 1, kind="trusted_link"))
            position = closing + 1
        else:
            position = marker + 2


def _break_reference_definitions(text: str) -> str:
    """Break definition syntax with an invisible separator, never a deletion.

    Discord has no reference-style links, so a line such as
    ``[label]: destination`` is ordinary text. The URL in it is neutralised by
    the catch-all pass; this pass additionally stops a CommonMark renderer from
    resolving the label against the same line.
    """
    pieces: list[str] = []
    position = 0
    while True:
        marker = text.find("]:", position)
        if marker < 0:
            pieces.append(text[position:])
            return "".join(pieces)
        cursor = marker + 2
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        destination = False
        if cursor < len(text):
            if text[cursor] in "</":
                destination = True
            else:
                end = cursor
                while end < len(text) and not text[end].isspace() and text[end] not in "()[]<>":
                    end += 1
                token = text[cursor:end]
                destination = any(character in token for character in ":/.")
        pieces.append(text[position : marker + 2])
        if destination and not text.startswith(_ZERO_WIDTH_SPACE, marker + 2):
            pieces.append(_ZERO_WIDTH_SPACE)
        pieces.append(text[marker + 2 : cursor])
        position = cursor


def _neutralize_plain(text: str) -> str:
    """Apply the parse-independent catch-all passes to ordinary text."""
    text = text.replace("](", f"]{_ZERO_WIDTH_SPACE}(")
    text = _break_reference_definitions(text)

    pieces: list[str] = []
    position = 0
    while True:
        scheme = text.find("://", position)
        if scheme < 0:
            pieces.append(text[position:])
            break
        scheme_end = scheme + 3
        pieces.append(text[position:scheme_end])
        if not text.startswith(_ZERO_WIDTH_SPACE, scheme_end):
            pieces.append(_ZERO_WIDTH_SPACE)
        position = scheme_end
    text = "".join(pieces)

    pieces = []
    last = 0
    position = 0
    while True:
        angle = text.find("<", position)
        if angle < 0:
            break
        cursor = angle + 1
        scheme_end = cursor
        while scheme_end < len(text) and (text[scheme_end].isalnum() or text[scheme_end] in "+.-"):
            scheme_end += 1
        if (
            scheme_end > cursor
            and text.startswith("://", scheme_end)
            and not text.startswith(_ZERO_WIDTH_SPACE, cursor)
        ):
            pieces.append(text[last:cursor])
            pieces.append(_ZERO_WIDTH_SPACE)
            last = cursor
            position = cursor + 1
        else:
            position = angle + 1
    pieces.append(text[last:])
    return "".join(pieces)


def _neutralize_address(address: str) -> str:
    """Make an email autolink non-clickable while keeping it readable."""
    at_sign = address.find("@")
    if at_sign >= 0 and not address.startswith(_ZERO_WIDTH_SPACE, at_sign + 1):
        return f"{address[: at_sign + 1]}{_ZERO_WIDTH_SPACE}{address[at_sign + 1:]}"
    return address


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


def _close_open_fence(text: str, available: int) -> str:
    """Return at most ``available`` characters with an open fence closed.

    A cut inside a fenced block appends the opening marker so the delivered
    chunk renders as code. When the shorter cut falls outside the fence, the
    original prefix is safe and is returned unchanged.
    """
    prefix = text[:available]
    marker = _open_fence_marker(prefix)
    if marker is None:
        return prefix

    shorter = text[: max(0, available - len(marker) - 1)]
    shorter_marker = _open_fence_marker(shorter)
    if shorter_marker is None:
        return prefix
    return f"{shorter}\n{shorter_marker}"


def _truncate_to_limit(text: str, limit: int, original_length: int | None = None) -> str:
    """Truncate text to ``limit`` characters with the visible Discord notice."""
    notice = truncation_notice(len(text) if original_length is None else original_length)
    available = limit - len(notice)
    if available <= 0:
        return text[:limit]
    if len(text) <= available:
        return text
    return f"{_close_open_fence(text, available)}{notice}"


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
    fence_free = not _has_fence_pair_candidate(message)

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

        before_split, after_split = split_fence_aware(
            remaining,
            limit,
            split_index,
            fence_free=fence_free,
        )

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
        chunk_text = sanitize_for_discord(chunk, citations)
        content = f"{prefix_text}{chunk_text}" if index == 0 and prefix_text else chunk_text
        if len(content) > MESSAGE_LIMIT:
            available = MESSAGE_LIMIT - 3
            content = f"{_close_open_fence(content, available)}..."
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
    """One protected fenced code block, including its opening and closing lines."""

    start: int
    content_start: int
    end: int
    marker: str
    language: str


def _make_fence_span(text: str, start: int, marker: str, end: int) -> _FenceSpan:
    """Build a split-time fence span and extend its end through a newline."""
    trailing = re.match(r"[ \t]*(?:\r\n|\n|\r)", text[end:])
    if trailing:
        end += trailing.end()
    content_start = text.find("\n", start + len(marker))
    if content_start == -1 or content_start >= end:
        content_start = min(start + len(marker), end)
    else:
        content_start += 1
    language = text[start + len(marker) :].split("\n", 1)[0].strip()
    return _FenceSpan(
        start=start,
        content_start=content_start,
        end=end,
        marker=marker,
        language=language,
    )


def _discord_fence_spans(text: str) -> list[_FenceSpan]:
    """Pair backtick runs the way Discord does, for chunk boundaries only.

    The sanitiser never uses these spans. Discord opens and closes a code
    block at a run of at least three backticks anywhere in a line, while
    CommonMark requires a line start. A split that follows the CommonMark
    span would cut a block Discord still renders, so the historical pairing
    (equal-length runs, outermost first) decides only where a chunk ends.
    This scan is linear and replaces the old cubic backreference regex.
    """
    runs: list[tuple[int, int]] = []
    position = 0
    while position < len(text):
        if text[position] != "`":
            position += 1
            continue
        start = position
        while position < len(text) and text[position] == "`":
            position += 1
        if position - start >= _FENCE_MARKER_LENGTH and not _is_escaped(text, start):
            runs.append((start, position))

    pending: dict[int, int] = {}
    pairs: list[tuple[int, int]] = []
    for start, end in runs:
        length = end - start
        if length in pending:
            opening = pending.pop(length)
            pairs.append((opening, end))
            for inner_length in [key for key, value in pending.items() if value > opening]:
                del pending[inner_length]
        else:
            pending.setdefault(length, start)

    pairs.sort(key=lambda pair: (pair[0], -pair[1]))
    spans: list[_FenceSpan] = []
    last_end = -1
    for start, end in pairs:
        if start < last_end:
            continue
        marker = text[start : start + (end - start)]
        marker_length = 0
        while marker_length < len(marker) and marker[marker_length] == "`":
            marker_length += 1
        spans.append(_make_fence_span(text, start, text[start : start + marker_length], end))
        last_end = end
    return spans


def _has_fence_pair_candidate(text: str) -> bool:
    """Return True when at least two backtick runs of length three exist."""
    runs = 0
    position = 0
    while position < len(text):
        if text[position] != "`":
            position += 1
            continue
        start = position
        while position < len(text) and text[position] == "`":
            position += 1
        if position - start >= _FENCE_MARKER_LENGTH:
            runs += 1
            if runs >= _CLOSING_DELIMITER_COUNT:
                return True
    return False


def _fence_spans(text: str) -> list[_FenceSpan]:
    """Return fenced spans for split placement.

    The shared code-region filter supplies protected fences from the block
    grammar; inline code spans do not affect a split. When no fence is
    protected, a Discord-style pairing keeps the historical chunk boundaries
    for blocks CommonMark does not recognise. Those extra spans never
    suppress sanitisation.
    """
    if not _has_fence_pair_candidate(text):
        return []
    protected = [
        _FenceSpan(
            start=region.start,
            content_start=region.content_start,
            end=region.end,
            marker=region.marker,
            language=region.language,
        )
        for region in _filtered_code_regions(_parse_markdown(text, include_inline=False))
        if region.kind == "fence"
    ]
    if protected:
        return protected
    return _discord_fence_spans(text)


def _open_fence_marker(text: str) -> str | None:
    """Return the opening marker of the last unclosed backtick fence, if any."""
    if not text or "```" not in text:
        return None
    parse = _parse_markdown(text, include_inline=False)
    for fence in reversed(parse.fences):
        if fence.closed:
            continue
        if fence.marker.startswith("```"):
            return fence.marker
        return None
    return None


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
    *,
    fence_free: bool = False,
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
        fence_free: Set when the whole message has fewer than two backtick
            runs of fence length, so no suffix can contain a fence.

    Returns:
        The head and tail; the concatenation of both contains every line of
        ``message`` plus any fence markers needed to keep the code balanced.
    """
    if len(message) <= limit:
        return message, ""

    if preferred is None:
        preferred = max(1, limit - MESSAGE_BUFFER)
    preferred = min(max(1, preferred), limit, len(message) - 1)

    if fence_free:
        return message[:preferred], message[preferred:]

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


def is_inside_rendered_code(text: str, position: int) -> bool:
    """Return True when ``position`` falls inside code Discord renders."""
    return any(
        start <= position < end
        for start, end in ((r.start, r.end) for r in protected_code_regions(text))
    )


def _links_outside_regions(
    regions: list[_CodeRegion],
    links: list[_LinkSpan],
) -> list[_LinkSpan]:
    """Drop links that fall inside a protected region and sort the rest."""
    region_starts = [region.start for region in regions]
    filtered: list[_LinkSpan] = []
    for link in links:
        index = bisect_left(region_starts, link.start)
        if index > 0:
            region = regions[index - 1]
            if region.start <= link.start < region.end:
                continue
        filtered.append(link)
    filtered.sort(key=lambda link: link.start)
    return filtered


def _link_output(text: str, link: _LinkSpan, render: Any) -> str:
    """Return the sanitised replacement for one parser-reported link span."""
    if link.allowed or link.kind in {"bare", "trusted_link"}:
        return text[link.start : link.end]
    if link.kind == "email_autolink":
        return _neutralize_address(link.destination)
    if link.kind == "uri_autolink":
        return _neutralize_url(link.destination)
    return render(link.label_start, link.label_end)


@dataclass(frozen=True)
class _RenderIndex:
    """Sorted spans and their start offsets for one render pass."""

    regions: list[_CodeRegion]
    region_starts: list[int]
    links: list[_LinkSpan]
    link_starts: list[int]


def _next_event(
    position: int,
    end: int,
    index: _RenderIndex,
) -> tuple[int, int, int | None, bool]:
    """Return the next region or link boundary at or after ``position``."""
    region_index = bisect_left(index.region_starts, position)
    while region_index < len(index.regions) and index.regions[region_index].start < position:
        region_index += 1
    link_index = bisect_left(index.link_starts, position)
    while link_index < len(index.links) and index.links[link_index].start < position:
        link_index += 1
    next_region = (
        index.regions[region_index].start
        if region_index < len(index.regions) and index.regions[region_index].start < end
        else None
    )
    next_link = (
        index.links[link_index].start
        if link_index < len(index.links) and index.links[link_index].start < end
        else None
    )
    if next_link is not None and (next_region is None or next_link <= next_region):
        return region_index, link_index, next_link, True
    return region_index, link_index, next_region, False


def _render_sanitized(
    text: str,
    regions: list[_CodeRegion],
    links: list[_LinkSpan],
) -> str:
    """Rewrite parser spans and apply the catch-all passes outside code."""
    region_starts = [region.start for region in regions]
    filtered_links = _links_outside_regions(regions, links)
    index = _RenderIndex(
        regions=regions,
        region_starts=region_starts,
        links=filtered_links,
        link_starts=[link.start for link in filtered_links],
    )

    def render(start: int, end: int) -> str:
        pieces: list[str] = []
        position = start
        while position < end:
            region_index = bisect_left(region_starts, position)
            if region_index > 0:
                region = regions[region_index - 1]
                if region.start <= position < region.end:
                    stop = min(end, region.end)
                    pieces.append(text[position:stop])
                    position = stop
                    continue
            region_index, link_index, next_start, is_link = _next_event(
                position,
                end,
                index,
            )
            if next_start is None:
                pieces.append(_neutralize_plain(text[position:end]))
                break
            if next_start > position:
                pieces.append(_neutralize_plain(text[position:next_start]))
                position = next_start
                continue
            if is_link:
                link = filtered_links[link_index]
                pieces.append(_link_output(text, link, render))
                position = link.end
                continue
            region = regions[region_index]
            stop = min(end, region.end)
            pieces.append(text[position:stop])
            position = stop
        return "".join(pieces)

    return render(0, len(text))


def sanitize_model_output(text: str, citations: dict[str, str] | None = None) -> str:
    """Neutralise mentions and untrusted links in model output.

    tree-sitter-markdown supplies the code regions and the links it can
    recognise. Code protection is conservative: only an exactly-three-backtick
    closed fence with no other triple-backtick run outside it, or a closed
    inline code span whose opener is not backslash-escaped, keeps its content.
    Inside those regions nothing is rewritten. Everywhere else the parser's
    inline links, images, and autolinks are replaced with their label text,
    and three catch-all passes then break ``](``, add a zero-width space after
    every ``://``, and separate ``<`` from a following URL scheme. The passes
    are linear, need no fixed-point loop, and do not depend on a parse, so
    nesting or a construct the parser misses cannot leave a live link.

    A link or bare URL that exactly matches a trusted citation URL is left
    clickable. Definition-shaped lines such as ``[label]: destination`` stay
    in the text; their URL is neutralised and an invisible separator stops a
    CommonMark renderer from resolving them as reference links. Mention
    neutralisation applies everywhere, including inside code.

    Args:
        text: Model-generated text bound for Discord.
        citations: Optional citation map. Entries carrying an
            ``untrusted_urls`` set are treated as labels only.

    Returns:
        Text with mentions and untrusted links neutralised.
    """
    if not text:
        return ""
    if not any(marker in text for marker in ("](", "://", "<", "@")):
        return text

    allowed_urls = {
        str(url).strip() for url in renderable_citations(citations).values() if str(url).strip()
    }
    parse = _parse_markdown(text)
    regions = _filtered_code_regions(parse)
    links = _link_spans(parse, allowed_urls)
    links.extend(_allowed_bare_url_spans(text, allowed_urls))
    links.extend(_allowed_markdown_link_spans(text, allowed_urls))
    sanitized = _render_sanitized(text, regions, links)

    sanitized = _RAW_MENTION_PATTERN.sub(
        lambda match: f"<{match.group(1)}{_ZERO_WIDTH_SPACE}{match.group(2)}>",
        sanitized,
    )
    return sanitized.replace("@everyone", f"@{_ZERO_WIDTH_SPACE}everyone").replace(
        "@here", f"@{_ZERO_WIDTH_SPACE}here"
    )


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
