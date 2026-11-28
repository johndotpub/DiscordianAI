"""Regression tests for the reliability hardening batch."""

import asyncio
import gc
import logging

import pytest

from src.api_validation import log_validation_results
from src.caching import RequestDeduplicator, _generate_scoped_key
from src.health_checks import APIHealthMonitor


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
