"""Shared text truncation that keeps each caller's existing notice wording."""


def truncate_with_notice(text: str, limit: int, notice: str) -> tuple[str, bool]:
    """Truncate text to a character limit and append the caller's notice.

    Args:
        text: Text to truncate.
        limit: Maximum number of characters to keep before the notice.
        notice: Text appended after the kept characters when truncation occurs.

    Returns:
        A tuple of the resulting text and whether truncation happened.
    """
    if len(text) <= limit:
        return text, False
    return f"{text[:limit]}{notice}", True
