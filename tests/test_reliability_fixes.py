"""Regression tests for the reliability hardening batch."""

import asyncio
import gc
import logging
import socket

import pytest

from src.api_validation import log_validation_results
from src.caching import RequestDeduplicator, _generate_scoped_key
from src.health_checks import APIHealthMonitor
from src.web_scraper import is_scrapable_url, scrape_url_content, scrape_urls


@pytest.mark.asyncio
async def test_dns_timeout_treats_host_as_unresolvable(monkeypatch, caplog):
    """A blackholed resolver must fail fast instead of hanging the scrape path."""

    async def slow_lookup(_hostname):
        await asyncio.sleep(10)
        return []

    monkeypatch.setattr("src.web_scraper._lookup_hostname", slow_lookup)
    monkeypatch.setattr("src.web_scraper.RESOLVE_TIMEOUT_SECONDS", 0.05)

    with caplog.at_level(logging.WARNING, logger="src.web_scraper"):
        result = await asyncio.wait_for(
            is_scrapable_url("https://slow.example/page?token=abc"),
            timeout=1.0,
        )

    assert result is False
    assert "slow.example" in caplog.text
    assert "token=abc" not in caplog.text


@pytest.mark.asyncio
async def test_scrape_urls_continues_after_one_url_raises(caplog):
    """One failing page must not discard successful siblings or leak its query."""
    bad_url = "https://bad.example/secret?token=abc"
    good_url = "https://good.example/page"

    async def scrape(url, logger=None, **_kwargs):
        if url == bad_url:
            msg = "page exploded"
            raise RuntimeError(msg)
        return "good content"

    with caplog.at_level(logging.WARNING, logger="src.web_scraper"):
        results = await scrape_urls(
            [bad_url, good_url],
            logging.getLogger("test.reliability"),
            max_urls=3,
            deadline_seconds=2,
            scrape_func=scrape,
        )

    assert [url for url, _content in results] == [good_url]
    assert "https://bad.example/secret" in caplog.text
    assert "token=abc" not in caplog.text


@pytest.mark.asyncio
async def test_failed_leader_lets_follower_run_its_own_request(caplog):
    """A failed leader wakes followers instead of sharing a dead future."""
    deduplicator = RequestDeduplicator()
    leader_started = asyncio.Event()
    release_leader = asyncio.Event()
    follower_calls = 0

    async def leader_work():
        leader_started.set()
        await release_leader.wait()
        msg = "leader failed"
        raise ValueError(msg)

    async def follower_work():
        nonlocal follower_calls
        follower_calls += 1
        return "follower result"

    with caplog.at_level(logging.ERROR, logger="asyncio"):
        leader = asyncio.create_task(deduplicator.deduplicate_request("shared", leader_work))
        await asyncio.wait_for(leader_started.wait(), timeout=1.0)
        follower = asyncio.create_task(deduplicator.deduplicate_request("shared", follower_work))
        await asyncio.sleep(0)

        release_leader.set()
        with pytest.raises(ValueError, match="leader failed"):
            await leader
        result = await asyncio.wait_for(follower, timeout=1.0)

    assert result == "follower result"
    assert follower_calls == 1
    gc.collect()
    await asyncio.sleep(0)
    assert "Future exception was never retrieved" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_leader_lets_follower_run_its_own_request():
    """Cancelling the leader must not cancel a follower's unrelated request."""
    deduplicator = RequestDeduplicator()
    leader_started = asyncio.Event()

    async def leader_work():
        leader_started.set()
        await asyncio.sleep(10)
        return "leader"

    async def follower_work():
        return "follower result"

    leader = asyncio.create_task(deduplicator.deduplicate_request("shared", leader_work))
    await asyncio.wait_for(leader_started.wait(), timeout=1.0)
    follower = asyncio.create_task(deduplicator.deduplicate_request("shared", follower_work))
    await asyncio.sleep(0)

    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    result = await asyncio.wait_for(follower, timeout=1.0)

    assert result == "follower result"


class _RaisingMonitor(APIHealthMonitor):
    """Health monitor whose OpenAI check always raises."""

    async def check_openai_health(self, *_args, **_kwargs):
        msg = "checker exploded"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_raising_health_checker_is_reported_as_unhealthy():
    """A raised checker becomes an unhealthy result instead of disappearing."""
    monitor = _RaisingMonitor()

    results = await monitor.run_all_health_checks({"openai": object()}, {})

    assert set(results) == {"openai"}
    result = results["openai"]
    assert result.status == "unhealthy"
    assert result.error == "check raised RuntimeError"
    assert result.details["error_type"] == "RuntimeError"
    assert result.response_time_ms >= 0
    assert monitor.metrics["openai"].failed_checks == 1


@pytest.mark.asyncio
async def test_scrape_logs_redact_credentials_and_query(monkeypatch, caplog):
    """Scraper logs must not expose URL userinfo, query strings, or fragments."""

    async def failing_lookup(_hostname):
        msg = "no such host"
        raise socket.gaierror(msg)

    monkeypatch.setattr("src.web_scraper._lookup_hostname", failing_lookup)
    url = "https://alice:s3cret@private.example/path?token=abc#fragment"

    with caplog.at_level(logging.DEBUG, logger="src.web_scraper"):
        result = await scrape_url_content(url)

    assert result is None
    assert "alice" not in caplog.text
    assert "s3cret" not in caplog.text
    assert "token=abc" not in caplog.text
    assert "fragment" not in caplog.text
    assert "private.example" in caplog.text


def test_api_validation_logs_redact_credentials_and_query(caplog):
    """Configured API URLs are logged without userinfo or query secrets."""
    config = {
        "DISCORD_TOKEN": "discord-token",
        "OPENAI_API_KEY": "sk-" + "a" * 32,
        "OPENAI_API_URL": "https://alice:s3cret@gateway.example/v1?token=abc#fragment",
    }

    with caplog.at_level(logging.WARNING, logger="src.api_validation"):
        log_validation_results(config, logging.getLogger("src.api_validation"))

    assert "alice" not in caplog.text
    assert "s3cret" not in caplog.text
    assert "token=abc" not in caplog.text
    assert "fragment" not in caplog.text
    assert "gateway.example" in caplog.text


def test_unscoped_cache_key_is_uncached():
    """A request without conversation or user identity has no safe cache scope."""
    context = {"model": "gpt-test", "system_message": "test"}

    assert _generate_scoped_key("question", context, salt="test-salt") is None
