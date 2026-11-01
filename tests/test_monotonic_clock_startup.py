"""Regression tests for monotonic timestamps on a freshly started host.

A monotonic clock counts from boot. On a CI runner or a fresh container that
value can be smaller than the window being measured, so a timestamp taken in
the past may be negative. Zero is the only value that means "never".
"""

import logging
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from src.health_server import create_health_app
from src.rate_limits import RateLimiter


class _Breaker:
    """Minimal breaker snapshot provider for the health endpoint."""

    def __init__(self, last_success_time: float) -> None:
        self._last_success_time = last_success_time

    def snapshot(self) -> dict:
        """Return a closed breaker with the supplied last success time."""
        return {
            "state": "CLOSED",
            "consecutive_failures": 0,
            "last_failure_time": 0.0,
            "last_success_time": self._last_success_time,
        }


def _health_app(openai_success: float, perplexity_success: float):
    """Build a ready health app with explicit breaker snapshots."""
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.guilds = []
    bot.latency = 0.05
    deps = {
        "bot": bot,
        "client": MagicMock(),
        "perplexity_client": MagicMock(),
        "config": {
            "OPENAI_API_KEY": "sk-test-key",
            "PERPLEXITY_API_KEY": "pplx-test-key",
        },
        "circuit_breakers": {
            "openai": _Breaker(openai_success),
            "perplexity": _Breaker(perplexity_success),
        },
    }
    return create_health_app(deps)


def test_first_request_on_young_clock_starts_the_window():
    """The first request records a timestamp even when uptime is below the window."""
    logger = logging.getLogger("test.monotonic.rate_limit")

    with patch("src.rate_limits.time.monotonic", return_value=30.0):
        limiter = RateLimiter()
        assert limiter.check_rate_limit(12345, 3, 60, logger) is True
        assert limiter.last_command_timestamps[12345] == 30.0
        assert limiter.last_command_count[12345] == 1

        assert limiter.check_rate_limit(12345, 3, 60, logger) is True
        assert limiter.check_rate_limit(12345, 3, 60, logger) is True
        assert limiter.check_rate_limit(12345, 3, 60, logger) is False

    assert limiter.last_command_timestamps[12345] == 30.0
    assert limiter.last_command_count[12345] == 3


def test_stale_success_on_young_clock_is_reported_but_healthy():
    """A success 3600 seconds ago is aged correctly but is not a failure."""
    with patch("src.health_server.time.monotonic", return_value=30.0):
        with TestClient(_health_app(-3570.0, 30.0)) as client:
            response = client.get("/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["providers"]["openai"]["status"] == "healthy", body
    assert body["providers"]["openai"]["last_success_age_seconds"] == 3600.0, body
    assert body["providers"]["openai"]["last_success_stale"] is True, body
    assert body["failing_providers"] == [], body


def test_never_succeeded_on_young_clock_is_not_stale():
    """Zero means never succeeded; it must not look like a stale success."""
    with patch("src.health_server.time.monotonic", return_value=30.0):
        with TestClient(_health_app(0.0, 0.0)) as client:
            response = client.get("/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["providers"]["openai"]["status"] == "healthy", body
    assert body["providers"]["openai"]["last_success_age_seconds"] is None, body
