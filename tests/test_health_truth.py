"""Regression tests for truthful health reporting and safe server startup."""

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from src.connection_pool import ConnectionPoolManager
from src.error_handling import get_circuit_breaker
from src.health_server import create_health_app

ROOT = Path(__file__).resolve().parents[1]

BIND_FAILURE_SCRIPT = """
import asyncio
import logging
import sys
from unittest.mock import MagicMock

from src.health_server import HealthServer

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def _deps():
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.guilds = []
    bot.latency = 0.05
    return {
        "bot": bot,
        "client": MagicMock(),
        "perplexity_client": MagicMock(),
        "config": {"HEALTH_ENABLED": True},
    }


async def main():
    server = HealthServer(_deps(), host="127.0.0.1", port=int(sys.argv[1]))
    await server.start()
    print("BOT_ALIVE", flush=True)
    await asyncio.sleep(0.05)
    await server.stop()


asyncio.run(main())
"""


class _FakePoolManager:
    """Minimal pool manager that returns JSON-safe metrics."""

    def get_pool_metrics(self):
        return {
            "openai": {
                "status": "active",
                "max_connections": 50,
                "max_keepalive": 10,
                "http2_enabled": True,
            },
            "perplexity": {
                "status": "active",
                "max_connections": 30,
                "max_keepalive": 5,
                "http2_enabled": True,
            },
        }


def _deps(
    *,
    connected=True,
    has_openai=True,
    has_perplexity=True,
    latency=0.05,
    pool_manager=None,
):
    """Create dependency data for the health app."""
    bot = MagicMock()
    bot.is_ready.return_value = connected
    bot.guilds = [MagicMock(), MagicMock()]
    bot.latency = latency

    config = {
        "OPENAI_API_KEY": "sk-test-key" if has_openai else None,
        "PERPLEXITY_API_KEY": "pplx-test-key" if has_perplexity else None,
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "sonar-pro",
        "HEALTH_ENABLED": True,
    }

    deps = {
        "bot": bot,
        "client": MagicMock() if has_openai else None,
        "perplexity_client": MagicMock() if has_perplexity else None,
        "config": config,
    }
    if pool_manager is not None:
        deps["connection_pool_manager"] = pool_manager
    return deps


def _open_provider_breakers():
    """Leave both providers observably failing, with no recent success."""
    for provider in ("openai", "perplexity"):
        breaker = get_circuit_breaker(provider)
        breaker.state = "OPEN"
        breaker.failure_count = 5
        breaker.last_failure_time = time.monotonic()
        breaker.last_success_time = 0.0


def test_health_reports_failing_providers_instead_of_healthy():
    """/health must not claim healthy while provider breakers are open."""
    _open_provider_breakers()
    app = create_health_app(_deps())

    with TestClient(app) as client:
        response = client.get("/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "unhealthy", body
    assert set(body["failing_providers"]) == {"openai", "perplexity"}, body
    assert body["providers"]["openai"]["state"] == "OPEN", body
    assert body["providers"]["perplexity"]["state"] == "OPEN", body


def test_readiness_reports_not_ready_when_providers_are_failing():
    """/health/ready must reflect provider failures, not just client identity."""
    _open_provider_breakers()
    app = create_health_app(_deps())

    with TestClient(app) as client:
        response = client.get("/health/ready")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "not_ready", body
    assert set(body["failing_providers"]) == {"openai", "perplexity"}, body


def test_stale_success_degrades_health_and_keeps_configured_separate():
    """A closed breaker with an old success is still not healthy."""
    breaker = get_circuit_breaker("openai")
    breaker.state = "CLOSED"
    breaker.failure_count = 0
    breaker.last_success_time = time.monotonic() - 3600
    app = create_health_app(_deps())

    with TestClient(app) as client:
        response = client.get("/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "degraded", body
    assert body["failing_providers"] == ["openai"], body
    assert body["services"]["openai"] == "configured", body
    assert body["services"]["openai_configured"] is True, body
    assert body["providers"]["openai"]["configured"] is True, body


def test_bind_failure_disables_health_server_without_killing_bot():
    """A busy port is contained: the process survives and logs once."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(  # noqa: S603 — fixed interpreter and script, no shell
            [sys.executable, "-c", BIND_FAILURE_SCRIPT, str(port)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    assert "BOT_ALIVE" in result.stdout
    disable_lines = [
        line for line in result.stderr.splitlines() if "health server disabled:" in line
    ]
    assert len(disable_lines) == 1, result.stderr


def test_http2_enabled_reflects_the_client_configuration():
    """HTTP/2 must be read from the real client, not a nonexistent attribute."""
    manager = ConnectionPoolManager()
    manager.create_http_client("openai")
    try:
        app = create_health_app(_deps(pool_manager=manager))
        with TestClient(app) as client:
            response = client.get("/health")

        body = response.json()
        assert body["services"]["pool"]["openai"]["http2_enabled"] is True, body
    finally:
        asyncio.run(manager.close_all())


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), 0.0])
def test_non_finite_or_zero_latency_does_not_cause_500(latency):
    """Invalid latency values are reported as null rather than crashing JSON."""
    app = create_health_app(_deps(latency=latency))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code != 500, response.text
    body = response.json()
    assert body["services"]["latency_ms"] is None, body


def test_health_json_keeps_every_documented_key():
    """New truthfulness fields must not remove the existing contract."""
    app = create_health_app(_deps(pool_manager=_FakePoolManager()))

    with TestClient(app) as client:
        response = client.get("/health")

    body = response.json()
    assert {
        "status",
        "mode",
        "model",
        "perplexity_model",
        "services",
        "circuit_breakers",
    } <= set(body)
    assert {
        "openai",
        "perplexity",
        "discord",
        "guilds",
        "latency_ms",
        "pool",
        "circuit_breakers",
    } <= set(body["services"])
    assert body["services"]["openai"] in {"configured", "not_configured"}
    assert body["services"]["perplexity"] in {"configured", "not_configured"}
