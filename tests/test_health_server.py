"""Tests for the HTTP health endpoint server."""

from unittest.mock import AsyncMock, MagicMock, patch

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
        "PERPLEXITY_MODEL": "sonar-pro",
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


@pytest.mark.asyncio
async def test_health_server_string_config_enabled():
    """Health server handles string HEALTH_ENABLED='true'."""
    deps = _mock_deps()
    deps["config"]["HEALTH_ENABLED"] = "true"
    with patch("uvicorn.Server") as mock_server_class:
        mock_server_instance = AsyncMock()
        mock_server_class.return_value = mock_server_instance
        server = HealthServer(deps, port=0)
        await server.start()
        await server.stop()


@pytest.mark.asyncio
async def test_health_server_stop_no_task():
    """Health server stop() is safe when no task exists."""
    deps = _mock_deps()
    server = HealthServer(deps)
    server._task = None
    await server.stop()


@pytest.mark.asyncio
async def test_health_server_start_stop():
    """Health server start and stop lifecycle."""
    deps = _mock_deps()
    with patch("uvicorn.Server") as mock_server_class:
        mock_server_instance = AsyncMock()
        mock_server_class.return_value = mock_server_instance

        server = HealthServer(deps, port=0)
        await server.start()
        await server.stop()
