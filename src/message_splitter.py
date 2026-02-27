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
    MAX_SPLIT_RECURSION,
    MENTION_PATTERN,
    MESSAGE_LIMIT,
)
from .discord_embeds import citation_embed_formatter

# ============================================================================
# CORE MESSAGE SENDING & SPLITTING
# ============================================================================


async def send_split_message(
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    _recursion_depth: int = 0,
) -> None:
    """Send messages with automatic splitting for Discord's message character limit."""
    logger = deps["logger"]

    # Recursion safety
    if _recursion_depth > MAX_SPLIT_RECURSION:
        logger.error(
            "Max split recursion reached (%d) for message length %d",
            MAX_SPLIT_RECURSION,
            len(message),
        )
        # Fallback send
        await channel.send(message[: MESSAGE_LIMIT - 50], suppress_embeds=suppress_embeds)
        trunc_msg = "[Message truncated due to recursion limit]"
        await channel.send(trunc_msg, suppress_embeds=suppress_embeds)
        return

    # Fits in one message
    if len(message) <= MESSAGE_LIMIT:
        await channel.send(message, suppress_embeds=suppress_embeds)
        return

    # Logical split
    safe_split_point = min(MESSAGE_LIMIT - 100, len(message) // 2)
    split_index = find_optimal_split_point(message, safe_split_point)

    if split_index >= MESSAGE_LIMIT:
        split_index = MESSAGE_LIMIT - 1

    before_split, after_split = adjust_split_for_code_blocks(message, split_index)

    # Send parts
    await channel.send(before_split, suppress_embeds=suppress_embeds)
    if after_split:
        await send_split_message(
            channel,
            after_split,
            deps,
            suppress_embeds=False,
            _recursion_depth=_recursion_depth + 1,
        )


async def send_split_message_with_embed(
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    embed: discord.Embed,
    citations: dict[str, str] | None = None,
) -> None:
    """Send a long message with citation embeds, maintaining citations across parts."""
    if len(message) > EMBED_SAFE_LIMIT:
        split_index = find_optimal_split_point(message, EMBED_SAFE_LIMIT)
        _, after_split = adjust_split_for_code_blocks(message, split_index)
    else:
        after_split = ""

    await channel.send("", embed=embed)

    if after_split.strip():
        message_part2 = after_split.strip()
        if citations:
            remaining_citations = {c: u for c, u in citations.items() if f"[{c}]" in message_part2}
            if remaining_citations:
                cont_embed, _ = citation_embed_formatter.create_citation_embed(
                    message_part2,
                    remaining_citations,
                    footer_text="🌐 Web search results (continued)",
                )
                if len(message_part2) > EMBED_LIMIT:
                    await send_split_message_with_embed(
                        channel,
                        message_part2,
                        deps,
                        cont_embed,
                        remaining_citations,
                    )
                else:
                    await channel.send("", embed=cont_embed)
            else:
                await send_split_message(channel, message_part2, deps)
        else:
            await send_split_message(channel, message_part2, deps)


async def send_formatted_message(
    channel: discord.TextChannel | discord.DMChannel,
    message: str,
    deps: dict[str, Any],
    suppress_embeds: bool = False,
    embed_data: dict | None = None,
) -> None:
    """Send formatted message to Discord, using extracted splitter logic."""
    logger = deps["logger"]

    if embed_data and "embed" in embed_data:
        embed = embed_data["embed"]
        clean_text = embed_data.get("clean_text", message)
        was_truncated = embed_data.get("embed_metadata", {}).get("was_truncated", False)

        if was_truncated:
            citations = embed_data.get("citations", {})
            await send_split_message_with_embed(channel, clean_text, deps, embed, citations)
            return

        try:
            await channel.send("", embed=embed)
        except discord.HTTPException:
            logger.exception("Failed to send embed, falling back to split text")
            await send_split_message(channel, message, deps, suppress_embeds)
    else:
        await send_split_message(channel, message, deps, suppress_embeds)


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

    # Truncate if needed
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "..."

    return cleaned


def extract_mentions(content: str) -> list[str]:
    """Extract user mentions from message content."""
    return MENTION_PATTERN.findall(content)


def format_user_context(user: Any, is_dm: bool) -> str:
    """Format user context for logging and error messages."""
    message_type = "DM" if is_dm else "channel message"
    return f"{message_type} from {user.name} (ID: {user.id})"


def count_links(text: str) -> int:
    """Count the number of links in text for embed suppression decisions."""
    # Count Discord hyperlinks [title](url)
    discord_links = len(re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text))

    # Count bare URLs
    bare_urls = len(BARE_URL_PATTERN.findall(text))

    return discord_links + bare_urls


def should_suppress_embeds(text: str, threshold: int = 2) -> bool:
    """Determine if embeds should be suppressed to reduce visual clutter."""
    return count_links(text) >= threshold


def sanitize_for_discord(text: str) -> str:
    """Sanitize text for safe Discord sending."""
    if not text:
        return ""

    # Remove potential Discord markdown exploits
    text = text.replace("@everyone", "@\u200beveryone")
    text = text.replace("@here", "@\u200bhere")

    # Ensure text isn't too long
    if len(text) > MESSAGE_LIMIT:
        text = text[:1997] + "..."

    return text


def parse_command_args(content: str, prefix: str = "!") -> tuple[str, list[str]]:
    """Parse command and arguments from message content."""
    if not content.startswith(prefix):
        return "", []

    parts = content[len(prefix) :].split()
    if not parts:
        return "", []

    return parts[0].lower(), parts[1:]


class MessageFormatter:
    """Utility class for consistent message formatting."""

    @staticmethod
    def error_message(user_mention: str, error_text: str) -> str:
        """Format error message with user mention."""
        return f"{user_mention} {error_text}"

    @staticmethod
    def rate_limit_message(user_mention: str, reset_time: float) -> str:
        """Format rate limit message."""
        return f"{user_mention} ⏱️ Please wait {reset_time:.1f}s before sending another message."

    @staticmethod
    def service_unavailable(service_name: str) -> str:
        """Format service unavailable message."""
        return f"🔧 {service_name} is temporarily unavailable. Please try again later."

    @staticmethod
    def processing_message() -> str:
        """Format processing indicator."""
        return "🤔 Processing your request..."

    @staticmethod
    def truncation_notice(original_length: int) -> str:
        """Format message truncation notice."""
        return f"\n\n[Message truncated from {original_length} characters for Discord limits]"
