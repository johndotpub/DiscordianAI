"""Failure and shutdown coverage for the health HTTP server.

A broken endpoint must never take the bot down, and a malformed breaker
snapshot must not be reported as a provider failure.
"""

import asyncio
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient
import uvicorn

from src.health_server import HealthServer, create_health_app


def _deps():
    """Create a ready bot and both API clients for health endpoint tests."""
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.guilds = []
    bot.latency = 0.05
    return {
        "bot": bot,
        "client": MagicMock(),
        "perplexity_client": MagicMock(),
        "config": {
            "OPENAI_API_KEY": "sk-test-key",
            "PERPLEXITY_API_KEY": "pplx-test-key",
            "HEALTH_ENABLED": True,
            "HEALTH_PROVIDER_STALE_SECONDS": 300,
        },
    }


class _Breaker:
    """Return a fixed breaker snapshot for the health endpoint."""

    def __init__(self, last_success_time: float) -> None:
        self._last_success_time = last_success_time

    def snapshot(self) -> dict:
        """Return a closed breaker that succeeded at the supplied time."""
        return {
            "state": "CLOSED",
            "consecutive_failures": 0,
            "last_failure_time": 0.0,
            "last_success_time": self._last_success_time,
        }


class _FakeServer:
    """Minimal uvicorn server with injectable failure points."""

    def __init__(self, *, started: bool = True, should_exit: bool = False) -> None:
        self.config = object()
        self.started = started
        self.should_exit = should_exit
        self.lifespan = None
        self.main_loop_calls = 0
        self.shutdown_calls = 0
        self.startup_error: BaseException | None = None
        self.main_loop_error: Exception | None = None
        self.shutdown_error: Exception | None = None

    async def startup(self) -> None:
        """Start the fake server or raise the configured startup failure."""
        if self.startup_error is not None:
            raise self.startup_error

    async def main_loop(self) -> None:
        """Run once, or raise the configured loop failure."""
        self.main_loop_calls += 1
        if self.main_loop_error is not None:
            raise self.main_loop_error
        self.should_exit = True

    async def shutdown(self) -> None:
        """Count shutdown calls, or raise the configured shutdown failure."""
        self.shutdown_calls += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error


class _AsyncLoadingConfig(uvicorn.Config):
    """A real uvicorn config whose load() is awaitable, as the server allows."""

    async def load(self) -> None:
        """Load synchronously inside an awaitable to exercise the async path."""
        super().load()


def _sync_config(app):
    return uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False)


def _async_config(app):
    return _AsyncLoadingConfig(
        app, host="127.0.0.1", port=0, log_level="warning", access_log=False
    )


def test_mapping_breaker_snapshots_are_reported_verbatim():
    """A breaker already stored as a mapping is shown without reinterpreting it."""
    deps = _deps()
    deps["circuit_breakers"] = {
        "openai": {"state": "OPEN", "consecutive_failures": 2},
        "perplexity": {"state": "CLOSED"},
        "unknown": object(),
    }

    with TestClient(create_health_app(deps)) as client:
        response = client.get("/health")

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
        with TestClient(create_health_app(deps)) as client:
            response = client.get("/health")

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

    with TestClient(create_health_app(deps)) as client:
        response = client.get("/health")

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
        with TestClient(create_health_app(deps)) as client:
            response = client.get("/health")

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

    with patch("uvicorn.Server") as server_class:
        await server.start()

    server_class.assert_not_called()
    assert server._task is None
    assert server._server is None


@pytest.mark.asyncio
async def test_missing_uvicorn_disables_the_endpoint_without_raising():
    """A missing optional dependency leaves the bot running with no endpoint."""
    deps = _deps()
    server = HealthServer(deps, port=0)

    with patch.dict(sys.modules, {"uvicorn": None}):
        await server.start()

    assert server._disabled_reason == "uvicorn is not installed"
    assert server._task is None
    assert server._server is None
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_system_exit_disables_the_endpoint_without_raising():
    """uvicorn's SystemExit is contained and its exit status is reported."""
    deps = _deps()
    fake_server = _FakeServer()
    fake_server.startup_error = SystemExit(2)

    with patch("uvicorn.Server", return_value=fake_server):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "uvicorn startup exited with status 2"
    assert server._task is None
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_exception_disables_the_endpoint_without_raising():
    """An unexpected startup exception is contained and reported as the reason."""
    deps = _deps()
    fake_server = _FakeServer()
    fake_server.startup_error = RuntimeError("startup exploded")

    with patch("uvicorn.Server", return_value=fake_server):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "startup exploded"
    assert server._task is None
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0


@pytest.mark.asyncio
async def test_startup_without_a_started_flag_disables_the_endpoint():
    """A server that never reports started is disabled instead of trusted."""
    deps = _deps()
    fake_server = _FakeServer(started=False)

    with patch("uvicorn.Server", return_value=fake_server):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._disabled_reason == "uvicorn did not report a started server"
    assert server._task is None
    assert server._server is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config_factory",
    [_sync_config, _async_config],
    ids=["sync-load", "async-load"],
)
async def test_startup_loads_the_lifespan_before_starting(config_factory):
    """The configured lifespan is created before startup, sync or awaitable."""
    server = HealthServer(_deps(), port=0)
    fake_server = _FakeServer()
    fake_server.config = config_factory(server._app)

    with patch("uvicorn.Server", return_value=fake_server):
        await server.start()
        task = server._task
        assert task is not None
        await asyncio.wait_for(task, timeout=1.0)

    assert fake_server.config.loaded is True
    assert fake_server.lifespan is not None
    assert fake_server.shutdown_calls == 1


@pytest.mark.asyncio
async def test_run_server_skips_main_loop_when_exit_requested_and_shuts_down():
    """An already-stopped server still gets its shutdown hook."""
    server = HealthServer(_deps())
    fake_server = _FakeServer(should_exit=True)

    await server._run_server(fake_server)

    assert fake_server.main_loop_calls == 0
    assert fake_server.shutdown_calls == 1


@pytest.mark.asyncio
async def test_run_server_logs_loop_failure_and_still_shuts_down(caplog):
    """A broken main loop is logged and still runs the shutdown hook."""
    server = HealthServer(_deps())
    fake_server = _FakeServer()
    fake_server.main_loop_error = RuntimeError("loop exploded")

    with caplog.at_level(logging.ERROR, logger="src.health_server"):
        await server._run_server(fake_server)

    assert fake_server.shutdown_calls == 1
    assert any(
        record.getMessage() == "Health server stopped unexpectedly" for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_server_does_not_shut_down_a_server_that_never_started():
    """A server that never reported started is not asked to shut down."""
    server = HealthServer(_deps())
    fake_server = _FakeServer(started=False, should_exit=True)

    await server._run_server(fake_server)

    assert fake_server.main_loop_calls == 0
    assert fake_server.shutdown_calls == 0


@pytest.mark.asyncio
async def test_run_server_logs_shutdown_failure_without_raising(caplog):
    """A shutdown failure is logged and cannot escape the owned task."""
    server = HealthServer(_deps())
    fake_server = _FakeServer(should_exit=True)
    fake_server.shutdown_error = RuntimeError("shutdown exploded")

    with caplog.at_level(logging.ERROR, logger="src.health_server"):
        await server._run_server(fake_server)

    assert fake_server.shutdown_calls == 1
    assert any(record.getMessage() == "Health server shutdown failed" for record in caplog.records)
