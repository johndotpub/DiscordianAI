"""Tests for the Perplexity fallback prompt used when scraping fails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.perplexity_processing import _build_fallback_message, _enhance_message_with_urls


def test_url_only_message_uses_single_url_overview_form():
    """A bare URL asks for an overview of that URL."""
    url = "https://example.com/article"
    logger = MagicMock()

    prompt = _build_fallback_message(url, [url], logger)

    assert prompt == (
        f"Please search for information about this URL and provide an overview: {url}"
    )


def test_text_plus_one_url_keeps_the_text_and_includes_the_url():
    """Text around a single URL is preserved alongside the URL."""
    url = "https://example.com/article"
    message = f"Can you summarise {url} for me?"
    logger = MagicMock()

    prompt = _build_fallback_message(message, [url], logger)

    assert prompt == (
        f"Please search for information about this URL to help answer: {message}\nURL: {url}"
    )
    assert message in prompt
    assert url in prompt


def test_several_urls_are_all_listed():
    """Every URL is listed when the message contains more than one."""
    urls = [
        "https://first.example/a",
        "https://second.example/b",
        "https://third.example/c",
    ]
    message = "Compare these pages please"
    logger = MagicMock()

    prompt = _build_fallback_message(message, urls, logger)

    assert prompt == (
        "Please search for information about these URLs to help answer: "
        f"{message}\nURLs: {', '.join(urls)}"
    )
    for url in urls:
        assert url in prompt


@pytest.mark.asyncio
async def test_failed_scrape_returns_fallback_prompt_containing_the_url():
    """A failed scrape hands the fallback prompt to the provider with the URL intact."""
    url = "https://blocked.example/article"
    message = f"What does {url} say?"
    logger = MagicMock()

    async def failed_scrape(*_args, **_kwargs):
        return None

    with (
        patch("src.perplexity_processing.is_scrapable_url", new=AsyncMock(return_value=True)),
        patch("src.perplexity_processing.scrape_url_content", new=failed_scrape),
    ):
        prompt = await _enhance_message_with_urls(message, [url], logger)

    assert prompt == (
        f"Please search for information about this URL to help answer: {message}\nURL: {url}"
    )
    assert url in prompt
