"""Tests for the HTTP health endpoint server."""

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.health_server import HealthServer, _detect_mode, create_health_app


def _mock_deps(connected=True, has_openai=True, has_perplexity=True):
    """Create a mock deps dict for health server tests."""
    bot = MagicMock()
    bot.is_ready.return_value = connected
    bot.guilds = [MagicMock(), MagicMock()]
    bot.latency = 0.05

    config = {
        "OPENAI_API_KEY": "sk-test-key" if has_openai else None,
        "PERPLEXITY_API_KEY": "pplx-test-key" if has_perplexity else None,
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "HEALTH_ENABLED": True,
        "HEALTH_HOST": "127.0.0.1",
        "HEALTH_PORT": 8080,
    }

    return {
        "bot": bot,
        "client": MagicMock() if has_openai else None,
        "perplexity_client": MagicMock() if has_perplexity else None,
        "config": config,
    }


def test_liveness_probe():
    """Liveness probe always returns 200 when process is alive."""
    deps = _mock_deps()
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_probe_ready():
    """Readiness probe returns 200 when bot is connected and has clients."""
    deps = _mock_deps(connected=True, has_openai=True)
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_probe_not_ready():
    """Readiness probe returns 503 when bot is not connected."""
    deps = _mock_deps(connected=False, has_openai=True)
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_health_endpoint_full():
    """Full health endpoint returns services summary."""
    deps = _mock_deps(connected=True, has_openai=True, has_perplexity=True)
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "hybrid"
    assert data["services"]["openai"] == "configured"
    assert data["services"]["perplexity"] == "configured"
    assert data["services"]["discord"] == "connected"


def test_health_endpoint_no_clients():
    """Health endpoint returns unhealthy when no API clients configured."""
    deps = _mock_deps(connected=True, has_openai=False, has_perplexity=False)
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503


def test_health_endpoint_openai_only():
    """Health endpoint reports openai_only mode correctly."""
    deps = _mock_deps(connected=True, has_openai=True, has_perplexity=False)
    app = create_health_app(deps)
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
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
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
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
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
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


class _FakeUvicornServer:
    """Minimal uvicorn server whose loop either returns or waits for cancellation."""

    def __init__(self, _config, *, block=False):
        self.config = object()
        self.started = True
        self.should_exit = False
        self.block = block
        self.main_loop_calls = 0
        self.main_loop_entered = asyncio.Event()
        self.release = asyncio.Event()
        self.shutdown_calls = 0

    async def startup(self):
        return None

    async def main_loop(self):
        self.main_loop_calls += 1
        self.main_loop_entered.set()
        if self.block:
            await self.release.wait()
        self.should_exit = True

    async def shutdown(self):
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_health_server_string_config_enabled():
    """String HEALTH_ENABLED='true' enables the server and runs its loop."""
    deps = _mock_deps()
    deps["config"]["HEALTH_ENABLED"] = "true"
    fake_server = _FakeUvicornServer(None)

    with patch("uvicorn.Server", return_value=fake_server):
        server = HealthServer(deps, port=0)
        await server.start()

        task = server._task
        assert task is not None
        await asyncio.wait_for(task, timeout=1.0)

    assert fake_server.main_loop_calls == 1
    assert fake_server.should_exit is True
    assert fake_server.shutdown_calls == 1

    await server.stop()


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
    """start() runs main_loop; stop() sets should_exit and cancels the task."""
    deps = _mock_deps()
    fake_server = _FakeUvicornServer(None, block=True)

    with patch("uvicorn.Server", return_value=fake_server):
        server = HealthServer(deps, port=0)
        await server.start()
        task = server._task

        assert task is not None
        await asyncio.wait_for(fake_server.main_loop_entered.wait(), timeout=1.0)
        assert fake_server.main_loop_calls == 1
        assert fake_server.should_exit is False
        assert not task.done()

        await server.stop()

    assert fake_server.should_exit is True
    assert task.cancelled()
    assert fake_server.shutdown_calls == 1
    assert server._task is None
    assert server._server is None


@pytest.mark.asyncio
async def test_health_server_startup_failure_disables_without_killing_bot(caplog):
    """A startup failure disables the endpoint, logs why, and leaves the bot alive."""
    deps = _mock_deps()
    fake_server = _FakeUvicornServer(None)
    fake_server.started = False

    async def fail_startup():
        msg = "address already in use"
        raise OSError(msg)

    fake_server.startup = fail_startup

    with (
        patch("uvicorn.Server", return_value=fake_server),
        caplog.at_level(logging.ERROR, logger="src.health_server"),
    ):
        server = HealthServer(deps, port=0)
        await server.start()

    assert server._task is None
    assert server._server is None
    assert server._disabled_reason == "address already in use"
    assert deps["bot"].is_ready() is True
    assert deps["bot"].close.call_count == 0
    assert any(
        "health server disabled: address already in use" in record.message
        for record in caplog.records
    )
