"""Tests for per-message URL, content, deadline and politeness budgets."""

import asyncio
import configparser
from pathlib import Path
import re
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest

from src.config import load_config
from src.perplexity_processing import _enhance_message_with_urls

REPO_ROOT = Path(__file__).resolve().parents[1]


def _scraper(content):
    async def scrape(url, logger=None, request_timeout=15, max_content_length=50000):
        return content(url) if callable(content) else content

    return scrape


@pytest.fixture(autouse=True)
def _no_real_politeness_sleep():
    with patch("src.web_scraper._add_respectful_delay", new=AsyncMock()):
        yield


@pytest.mark.asyncio
async def test_message_urls_are_capped_and_drops_are_logged():
    urls = [f"https://site{i}.example/page" for i in range(20)]
    scraped = []

    async def scrape(url, logger=None, request_timeout=15, max_content_length=50000):
        scraped.append(url)
        return f"content for {url}"

    logger = MagicMock()
    with patch("src.perplexity_processing.is_scrapable_url", new=AsyncMock(return_value=True)):
        with patch("src.perplexity_processing.scrape_url_content", new=scrape):
            enhanced = await _enhance_message_with_urls("Read these links", urls, logger)

    assert scraped == urls[:3]
    assert "content for https://site2.example/page" in enhanced
    assert urls[3] not in enhanced

    warnings = " ".join(str(call) for call in logger.warning.call_args_list)
    assert "17" in warnings
    assert "ignored" in warnings.lower()


@pytest.mark.asyncio
async def test_aggregate_scraped_text_stays_within_budget():
    urls = [f"https://page{i}.example/article" for i in range(3)]
    max_total = 1000
    logger = MagicMock()

    with patch("src.perplexity_processing.is_scrapable_url", new=AsyncMock(return_value=True)):
        with patch("src.perplexity_processing.scrape_url_content", new=_scraper("A" * 50000)):
            enhanced = await _enhance_message_with_urls(
                "Summarise these pages",
                urls,
                logger,
                max_urls=3,
                max_total_chars=max_total,
                deadline_seconds=5,
            )

    injected = enhanced.split("Contents:\n", 1)[1]
    assert len(injected) <= max_total
    assert "Content from https://page0.example/article" in injected


@pytest.mark.asyncio
async def test_deadline_returns_partial_content_and_logs_expiry():
    fast_url = "https://fast.example/article"
    slow_url = "https://slow.example/article"
    logger = MagicMock()

    async def scrape(url, logger=None, request_timeout=15, max_content_length=50000):
        if url == slow_url:
            await asyncio.sleep(5)
        return f"content for {url}"

    with patch("src.perplexity_processing.is_scrapable_url", new=AsyncMock(return_value=True)):
        with patch("src.perplexity_processing.scrape_url_content", new=scrape):
            enhanced = await _enhance_message_with_urls(
                "Read both pages",
                [fast_url, slow_url],
                logger,
                max_urls=3,
                deadline_seconds=0.05,
            )

    assert f"content for {fast_url}" in enhanced
    assert f"content for {slow_url}" not in enhanced
    warnings = " ".join(str(call) for call in logger.warning.call_args_list)
    assert "deadline" in warnings.lower()
    assert "partial" in warnings.lower()


@pytest.mark.asyncio
async def test_first_request_to_host_does_not_sleep_but_second_does():
    from src.web_scraper import scrape_urls

    urls = ["https://same.example/one", "https://same.example/two"]
    events = []

    async def scrape(url, logger=None, request_timeout=15, max_content_length=50000):
        events.append(("scrape", url))
        return f"content for {url}"

    async def record_delay():
        events.append(("delay",))

    with patch("src.web_scraper._add_respectful_delay", new=record_delay):
        results = await scrape_urls(
            urls,
            MagicMock(),
            max_urls=3,
            deadline_seconds=5,
            scrape_func=scrape,
        )

    assert events == [
        ("scrape", urls[0]),
        ("delay",),
        ("scrape", urls[1]),
    ]
    assert [url for url, _ in results] == urls


@pytest.mark.asyncio
async def test_distinct_hosts_overlap_while_same_host_stays_serial():
    from src.web_scraper import scrape_urls

    urls = [
        "https://alpha.example/one",
        "https://beta.example/one",
        "https://alpha.example/two",
    ]
    active_hosts = set()
    distinct_overlap = False
    same_host_overlap = False

    async def scrape(url, logger=None, request_timeout=15, max_content_length=50000):
        nonlocal distinct_overlap, same_host_overlap
        host = urlparse(url).hostname
        if host in active_hosts:
            same_host_overlap = True
        elif active_hosts:
            distinct_overlap = True
        active_hosts.add(host)
        try:
            await asyncio.sleep(0.05)
        finally:
            active_hosts.discard(host)
        return f"content for {url}"

    results = await scrape_urls(
        urls,
        MagicMock(),
        max_urls=3,
        deadline_seconds=2,
        scrape_func=scrape,
    )

    assert distinct_overlap is True
    assert same_host_overlap is False
    assert [url for url, _ in results] == urls


def test_scrape_budget_defaults_agree_everywhere(monkeypatch):
    keys = ("MAX_URLS_PER_MESSAGE", "MAX_TOTAL_SCRAPED_CHARS", "SCRAPE_DEADLINE_SECONDS")
    expected = {
        "MAX_URLS_PER_MESSAGE": 3,
        "MAX_TOTAL_SCRAPED_CHARS": 60000,
        "SCRAPE_DEADLINE_SECONDS": 20,
    }
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    loaded = load_config()
    for key in keys:
        assert loaded[key] == expected[key]

    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "config.ini.example")
    assert parser.getint("Default", "MAX_URLS_PER_MESSAGE") == expected["MAX_URLS_PER_MESSAGE"]
    assert (
        parser.getint("Default", "MAX_TOTAL_SCRAPED_CHARS") == expected["MAX_TOTAL_SCRAPED_CHARS"]
    )
    assert (
        parser.getfloat("Default", "SCRAPE_DEADLINE_SECONDS")
        == expected["SCRAPE_DEADLINE_SECONDS"]
    )

    docs = (REPO_ROOT / "docs" / "Configuration.md").read_text(encoding="utf-8")
    for key in keys:
        pattern = rf"`{key}`[^\n]*?\(default:\s*`?{expected[key]}`?\)"
        assert re.search(pattern, docs), f"{key} default missing from docs"
