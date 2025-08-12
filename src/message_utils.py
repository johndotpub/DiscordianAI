"""Message processing utilities for Discord bot.

This module contains utility functions for processing, formatting,
and splitting Discord messages in a clean and reusable way.
"""

import re

from .config import BARE_URL_PATTERN, MENTION_PATTERN


def find_optimal_split_point(message: str, target_index: int) -> int:
    """Find the best place to split a message near a target index.

    Prioritizes splitting at natural boundaries like newlines,
    sentences, or word boundaries to maintain readability.

    Args:
        message: The message to split
        target_index: Preferred split location

    Returns:
        Optimal split index
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
    """Detect code block boundaries in text.

    Args:
        text: Text to analyze

    Returns:
        List of (start, end) positions for code blocks
    """
    pattern = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def is_inside_code_block(position: int, code_blocks: list[tuple[int, int]]) -> bool:
    """Check if a position is inside a code block.

    Args:
        position: Character position to check
        code_blocks: List of (start, end) code block positions

    Returns:
        True if position is inside a code block
    """
    return any(start <= position <= end for start, end in code_blocks)


def adjust_split_for_code_blocks(message: str, split_point: int) -> tuple[str, str]:
    """Adjust message split to avoid breaking code blocks.

    Args:
        message: Original message
        split_point: Proposed split point

    Returns:
        Tuple of (before_split, after_split) adjusted for code blocks
    """
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


def clean_message_content(content: str, max_length: int = 100) -> str:
    """Clean and truncate message content for logging.

    Args:
        content: Raw message content
        max_length: Maximum length for display

    Returns:
        Cleaned and truncated content
    """
    if not content:
        return "[empty]"

    # Remove extra whitespace and newlines
    cleaned = re.sub(r"\s+", " ", content.strip())

    # Truncate if needed
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "..."

    return cleaned


def extract_mentions(content: str) -> list[str]:
    """Extract user mentions from message content.

    Args:
        content: Message content

    Returns:
        List of user IDs mentioned
    """
    return MENTION_PATTERN.findall(content)


def format_user_context(user, is_dm: bool) -> str:
    """Format user context for logging and error messages.

    Args:
        user: Discord user object
        is_dm: Whether this is a direct message

    Returns:
        Formatted context string
    """
    message_type = "DM" if is_dm else "channel message"
    return f"{message_type} from {user.name} (ID: {user.id})"


def count_links(text: str) -> int:
    """Count the number of links in text for embed suppression decisions.

    Args:
        text: Text to analyze

    Returns:
        Number of links found
    """
    # Count Discord hyperlinks [title](url)
    discord_links = len(re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text))

    # Count bare URLs
    bare_urls = len(BARE_URL_PATTERN.findall(text))

    return discord_links + bare_urls


def should_suppress_embeds(text: str, threshold: int = 2) -> bool:
    """Determine if embeds should be suppressed to reduce visual clutter.

    Args:
        text: Message text
        threshold: Link count threshold for suppression

    Returns:
        True if embeds should be suppressed
    """
    return count_links(text) >= threshold


def sanitize_for_discord(text: str) -> str:
    """Sanitize text for safe Discord sending.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text safe for Discord
    """
    if not text:
        return ""

    # Remove potential Discord markdown exploits
    text = text.replace("@everyone", "@\u200beveryone")
    text = text.replace("@here", "@\u200bhere")

    # Ensure text isn't too long
    if len(text) > 2000:
        text = text[:1997] + "..."

    return text


def parse_command_args(content: str, prefix: str = "!") -> tuple[str, list[str]]:
    """Parse command and arguments from message content.

    Args:
        content: Message content
        prefix: Command prefix

    Returns:
        Tuple of (command, args_list)
    """
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
