"""Failure and shutdown coverage for the health HTTP server.

A broken endpoint must never take the bot down, and a malformed breaker
snapshot must not be reported as a provider failure.
"""

from contextlib import contextmanager
import logging
import sys
from unittest.mock import patch

import pytest

from src.health_server import HealthServer, create_health_app
from tests.helpers import (
    FakeAppRunner,
    FakeBreaker,
    FakeSite,
    health_deps,
    request_health,
)

_Breaker = FakeBreaker


def _deps():
    """Create a ready bot and both API clients for health endpoint tests."""
    return health_deps(
        guilds=[],
        config={"HEALTH_PROVIDER_STALE_SECONDS": 300},
    )


@contextmanager
def _patch_server(fake_runner, fake_site):
    """Patch the aiohttp runner and site with injectable doubles."""
    with (
        patch("src.health_server.web.AppRunner", return_value=fake_runner),
        patch("src.health_server.web.TCPSite", return_value=fake_site),
    ):
        yield


def test_mapping_breaker_snapshots_are_reported_verbatim():
    """A breaker already stored as a mapping is shown without reinterpreting it."""
    deps = _deps()
    deps["circuit_breakers"] = {
        "openai": {"state": "OPEN", "consecutive_failures": 2},
        "perplexity": {"state": "CLOSED"},
        "unknown": object(),
    }

    response = request_health(create_health_app(deps), "/health")

    body = response.json()
    assert response.status_code == 503
    assert body["circuit_breakers"]["openai"] == {
        "state": "OPEN",
        "consecutive_failures": 2,
    }
    assert "unknown" not in body["circuit_breakers"]
    assert body["providers"]["openai"]["state"] == "OPEN"
    assert body["failing_providers"] == ["openai"]


@pytest.mark.parametrize(
    "threshold",
    ["not-a-number", 0, -5, float("inf"), float("nan")],
    ids=["text", "zero", "negative", "infinity", "nan"],
)
def test_invalid_stale_threshold_does_not_degrade_fresh_success(threshold):
    """A malformed or non-positive threshold falls back to the default."""
    deps = _deps()
    deps["config"]["HEALTH_PROVIDER_STALE_SECONDS"] = threshold
    deps["circuit_breakers"] = {
        "openai": _Breaker(1000.0),
        "perplexity": _Breaker(1000.0),
    }

    with patch("src.health_server.time.monotonic", return_value=1000.0):
        response = request_health(create_health_app(deps), "/health")

    body = response.json()
    assert response.status_code == 200
    assert body["providers"]["openai"]["status"] == "healthy"
    assert body["providers"]["perplexity"]["status"] == "healthy"


def test_non_numeric_breaker_counters_are_treated_as_never_failed():
    """Garbage counters in a wired snapshot do not crash or invent a failure."""
    deps = _deps()
    deps["circuit_breakers"] = {
        "openai": {
            "state": "CLOSED",
            "consecutive_failures": "many",
            "last_failure_time": "never",
            "last_success_time": None,
        },
        "perplexity": {"state": "CLOSED"},
    }

    response = request_health(create_health_app(deps), "/health")

    body = response.json()
    provider = body["providers"]["openai"]
    assert response.status_code == 200
    assert provider["consecutive_failures"] == 0
    assert provider["last_failure_time"] == 0.0
    assert provider["last_success_age_seconds"] is None
    assert provider["status"] == "healthy"


def test_wall_clock_success_is_aged_and_future_monotonic_is_not_ancient():
    """Wall-clock stamps are aged; a future monotonic reading is just new."""
    deps = _deps()
    deps["circuit_breakers"] = {
        "openai": _Breaker(1_699_999_900.0),
        "perplexity": _Breaker(200.0),
    }

    with (
        patch("src.health_server.time.monotonic", return_value=30.0),
        patch("src.health_server.time.time", return_value=1_700_000_000.0),
    ):
        response = request_health(create_health_app(deps), "/health")

    body = response.json()
    assert response.status_code == 200
    assert body["providers"]["openai"]["last_success_age_seconds"] == 100.0
    assert body["providers"]["perplexity"]["last_success_age_seconds"] == 0.0
    assert body["providers"]["openai"]["status"] == "healthy"
    assert body["providers"]["perplexity"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_disable_keeps_first_reason_and_start_stays_disabled(caplog):
    """The first diagnosis wins, is logged once, and no later start runs."""
    server = HealthServer(_deps(), port=0)

    with caplog.at_level(logging.ERROR, logger="src.health_server"):
        server._disable("first failure")
        server._disable("second failure")

    assert server._disabled_reason == "first failure"
    assert len(caplog.records) == 1

    with patch("src.health_server.web.AppRunner") as runner_class:
        await server.start()

    runner_class.assert_not_called()
    assert server._task is None
    assert server._server is None


@pytest.mark.asyncio
async def test_missing_aiohttp_disables_the_endpoint_without_raising():
    """A missing optional dependency leaves the bot running with no endpoint."""
    deps = _deps()
    server = HealthServer(deps, port=0)

    with patch.dict(sys.modules, {"aiohttp": None}):
        await server.start()

    assert server._disabled_reason == "aiohttp is not installed"
    assert server._task is None
    assert server._server is None
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_system_exit_disables_the_endpoint_without_raising():
    """A startup SystemExit is contained and its exit status is reported."""
    deps = _deps()
    fake_runner = FakeAppRunner()
    fake_site = FakeSite()
    fake_site.start_error = SystemExit(2)

    with _patch_server(fake_runner, fake_site):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "aiohttp startup exited with status 2"
    assert server._task is None
    assert fake_runner.cleanup_calls == 1
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_exception_disables_the_endpoint_without_raising():
    """An unexpected startup exception is contained and reported as the reason."""
    deps = _deps()
    fake_runner = FakeAppRunner()
    fake_site = FakeSite()
    fake_site.start_error = RuntimeError("startup exploded")

    with _patch_server(fake_runner, fake_site):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "startup exploded"
    assert server._task is None
    assert fake_runner.cleanup_calls == 1
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_without_a_listening_site_disables_the_endpoint():
    """A server that never reports a listening socket is disabled instead of trusted."""
    deps = _deps()
    fake_runner = FakeAppRunner()
    fake_runner.report_no_listener()
    fake_site = FakeSite()

    with _patch_server(fake_runner, fake_site):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "aiohttp did not report a started server"
    assert server._task is None
    assert server._server is None
    assert fake_runner.cleanup_calls == 1


@pytest.mark.asyncio
async def test_startup_setup_runs_before_the_site_starts():
    """The application lifecycle is prepared before the listener accepts traffic."""
    events = []

    class _OrderedRunner(FakeAppRunner):
        async def setup(self):
            events.append("setup")
            await super().setup()

    class _OrderedSite(FakeSite):
        async def start(self):
            events.append("start")
            await super().start()

    fake_runner = _OrderedRunner()
    fake_site = _OrderedSite()

    with _patch_server(fake_runner, fake_site):
        server = HealthServer(_deps(), port=0)
        await server.start()
        task = server._task
        assert task is not None
        await server.stop()

    assert events == ["setup", "start"]
    assert fake_runner.cleanup_calls == 1
    assert task.cancelled()


@pytest.mark.asyncio
async def test_run_server_cleans_up_a_server_that_was_already_stopping():
    """An already-stopped server still gets its cleanup hook."""
    server = HealthServer(_deps())
    fake_runner = FakeAppRunner()
    server._stop_event.set()

    await server._run_server(fake_runner)

    assert fake_runner.cleanup_calls == 1


class _FailingStopEvent:
    """Stop signal whose wait always raises the configured failure."""

    async def wait(self) -> None:
        """Raise the loop failure the owned task must report."""
        msg = "loop exploded"
        raise RuntimeError(msg)

    def set(self) -> None:
        """Accept the stop request; the wait path never observes it."""


@pytest.mark.asyncio
async def test_run_server_logs_wait_failure_and_still_cleans_up(caplog):
    """A broken wait is logged and still runs the cleanup hook."""
    server = HealthServer(_deps())
    fake_runner = FakeAppRunner()
    server._stop_event = _FailingStopEvent()

    with caplog.at_level(logging.ERROR, logger="src.health_server"):
        await server._run_server(fake_runner)

    assert fake_runner.cleanup_calls == 1
    assert any(
        record.getMessage() == "Health server stopped unexpectedly" for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_server_cleans_up_a_runner_with_no_bound_site():
    """A runner that never bound a site is released without raising."""
    server = HealthServer(_deps())
    fake_runner = FakeAppRunner()
    fake_runner.report_no_listener()
    server._stop_event.set()

    await server._run_server(fake_runner)

    assert fake_runner.cleanup_calls == 1


@pytest.mark.asyncio
async def test_run_server_logs_shutdown_failure_without_raising(caplog):
    """A shutdown failure is logged and cannot escape the owned task."""
    server = HealthServer(_deps())
    fake_runner = FakeAppRunner()
    fake_runner.cleanup_error = RuntimeError("shutdown exploded")
    server._stop_event.set()

    with caplog.at_level(logging.ERROR, logger="src.health_server"):
        await server._run_server(fake_runner)

    assert fake_runner.cleanup_calls == 1
    assert any(record.getMessage() == "Health server shutdown failed" for record in caplog.records)
