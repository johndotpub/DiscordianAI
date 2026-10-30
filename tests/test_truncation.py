"""Tests for the shared truncate-with-notice helper."""

from src.truncation import truncate_with_notice


def test_text_at_or_below_limit_is_unchanged():
    assert truncate_with_notice("exact", 5, "...") == ("exact", False)
    assert truncate_with_notice("short", 5, "...") == ("short", False)


def test_text_over_limit_keeps_limit_chars_and_appends_notice():
    assert truncate_with_notice("abcdef", 3, "...") == ("abc...", True)


def test_empty_notice_is_allowed_for_callers_that_send_it_separately():
    assert truncate_with_notice("abcdef", 3, "") == ("abc", True)
