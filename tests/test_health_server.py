"""Tests for the HTTP health endpoint server."""

import logging
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from src.health_server import HealthServer, _detect_mode, create_health_app
from tests.helpers import (
    FakeAppRunner,
    FakeSite,
    health_deps,
    health_server_port,
    request_health,
)

_mock_deps = health_deps


def test_liveness_probe():
    """Liveness probe always returns 200 when process is alive."""
    deps = _mock_deps()
    app = create_health_app(deps)

    response = request_health(app, "/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_probe_ready():
    """Readiness probe returns 200 when bot is connected and has clients."""
    deps = _mock_deps(connected=True, has_openai=True)
    app = create_health_app(deps)

    response = request_health(app, "/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_probe_not_ready():
    """Readiness probe returns 503 when bot is not connected."""
    deps = _mock_deps(connected=False, has_openai=True)
    app = create_health_app(deps)

    response = request_health(app, "/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_health_endpoint_full():
    """Full health endpoint returns services summary."""
    deps = _mock_deps(connected=True, has_openai=True, has_perplexity=True)
    app = create_health_app(deps)

    response = request_health(app, "/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "hybrid"
    assert data["services"]["openai"] == "configured"
    assert data["services"]["perplexity"] == "configured"
    assert data["services"]["discord"] == "connected"


@pytest.mark.parametrize("route", ["/health", "/health/live", "/health/ready"])
def test_trailing_slash_route_matches_the_base_route(route):
    """Probes with a trailing slash keep the same status and body."""
    with patch("src.health_server.time.monotonic", return_value=1000.0):
        base = request_health(create_health_app(_mock_deps(connected=True)), route)
        slash = request_health(create_health_app(_mock_deps(connected=True)), route + "/")

    assert slash.status_code == base.status_code, slash.text
    assert slash.json() == base.json()


def test_health_endpoint_no_clients():
    """Health endpoint returns unhealthy when no API clients configured."""
    deps = _mock_deps(connected=True, has_openai=False, has_perplexity=False)
    app = create_health_app(deps)

    response = request_health(app, "/health")

    assert response.status_code == 503


def test_health_endpoint_openai_only():
    """Health endpoint reports openai_only mode correctly."""
    deps = _mock_deps(connected=True, has_openai=True, has_perplexity=False)
    app = create_health_app(deps)

    response = request_health(app, "/health")

    data = response.json()
    assert data["mode"] == "openai_only"


def test_detect_mode_hybrid():
    """Mode detection returns hybrid when both keys present."""
    config = {"OPENAI_API_KEY": "sk-test", "PERPLEXITY_API_KEY": "pplx-test"}
    assert _detect_mode(config) == "hybrid"


def test_detect_mode_openai_only():
    """Mode detection returns openai_only with only OpenAI key."""
    config = {"OPENAI_API_KEY": "sk-test", "PERPLEXITY_API_KEY": None}
    assert _detect_mode(config) == "openai_only"


def test_detect_mode_perplexity_only():
    """Mode detection returns perplexity_only with only Perplexity key."""
    config = {"OPENAI_API_KEY": None, "PERPLEXITY_API_KEY": "pplx-test"}
    assert _detect_mode(config) == "perplexity_only"


def test_detect_mode_none():
    """Mode detection returns none with no keys."""
    config = {"OPENAI_API_KEY": None, "PERPLEXITY_API_KEY": None}
    assert _detect_mode(config) == "none"


@pytest.mark.asyncio
async def test_health_server_disabled():
    """Health server does not start when disabled in config."""
    deps = _mock_deps()
    deps["config"]["HEALTH_ENABLED"] = False
    server = HealthServer(deps)
    await server.start()
    assert server._task is None


def test_health_endpoint_disconnected_bot():
    """Health endpoint reports disconnected when bot is not ready."""
    deps = _mock_deps(connected=False, has_openai=True)
    app = create_health_app(deps)

    response = request_health(app, "/health")

    assert response.status_code == 503
    assert response.json()["services"]["discord"] == "disconnected"


def test_health_endpoint_pool_with_check_pool_health():
    """Health endpoint uses check_pool_health when get_pool_metrics unavailable."""
    pool_manager = MagicMock()
    del pool_manager.get_pool_metrics
    pool_manager.check_pool_health.return_value = {"status": "healthy"}
    deps = _mock_deps(connected=True, has_openai=True)
    deps["connection_pool_manager"] = pool_manager
    app = create_health_app(deps)

    response = request_health(app, "/health")

    assert response.status_code == 200
    assert response.json()["services"]["pool"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_server_already_running():
    """Health server start() is a no-op when already running."""
    deps = _mock_deps()
    server = HealthServer(deps)
    mock_task = MagicMock()
    mock_task.done.return_value = False
    server._task = mock_task
    await server.start()
    assert server._task is mock_task


@pytest.mark.asyncio
async def test_health_server_string_config_enabled():
    """String HEALTH_ENABLED='true' enables the server and runs its loop."""
    deps = _mock_deps()
    deps["config"]["HEALTH_ENABLED"] = "true"
    fake_runner = FakeAppRunner()
    fake_site = FakeSite()

    with (
        patch("src.health_server.web.AppRunner", return_value=fake_runner),
        patch("src.health_server.web.TCPSite", return_value=fake_site),
    ):
        server = HealthServer(deps, port=0)
        await server.start()

        task = server._task
        assert task is not None
        assert not task.done()
        assert fake_runner.setup_calls == 1
        assert fake_site.start_calls == 1

        await server.stop()

    assert task.cancelled()
    assert fake_runner.cleanup_calls == 1


@pytest.mark.asyncio
async def test_health_server_stop_no_task():
    """Health server stop() is safe when no task exists."""
    deps = _mock_deps()
    server = HealthServer(deps)
    server._task = None
    server._server = None

    await server.stop()

    assert server._task is None
    assert server._server is None


@pytest.mark.asyncio
async def test_health_server_start_stop():
    """start() binds the endpoint; stop() cancels the task and releases it."""
    deps = _mock_deps()
    server = HealthServer(deps, host="127.0.0.1", port=0)

    await server.start()
    task = server._task
    site = server._site

    assert task is not None
    assert site is not None
    assert not task.done()
    assert server._disabled_reason is None

    async with aiohttp.ClientSession() as session:
        port = health_server_port(server)
        async with session.get(f"http://127.0.0.1:{port}/health/live") as response:
            assert response.status == 200
            assert response.content_type == "application/json"
            body = await response.json()
    assert body["status"] == "alive"

    await server.stop()

    assert task.cancelled()
    assert server._task is None
    assert server._server is None
    assert server._site is None


@pytest.mark.asyncio
async def test_health_server_startup_failure_disables_without_killing_bot(caplog):
    """A startup failure disables the endpoint, logs why, and leaves the bot alive."""
    deps = _mock_deps()
    fake_runner = FakeAppRunner()
    fake_site = FakeSite()
    fake_site.start_error = OSError("address already in use")

    with (
        patch("src.health_server.web.AppRunner", return_value=fake_runner),
        patch("src.health_server.web.TCPSite", return_value=fake_site),
        caplog.at_level(logging.ERROR, logger="src.health_server"),
    ):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._task is None
    assert server._server is None
    assert server._site is None
    assert server._disabled_reason == "address already in use"
    assert fake_runner.cleanup_calls == 1
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0
    assert any(
        "health server disabled: address already in use" in record.message
        for record in caplog.records
    )
