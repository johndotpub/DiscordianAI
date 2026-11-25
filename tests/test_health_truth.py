"""Regression tests for truthful health reporting and safe server startup."""

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.connection_pool import ConnectionPoolManager
from src.error_handling import get_circuit_breaker
from src.health_server import create_health_app
from tests.helpers import health_deps, request_health

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


_deps = health_deps


def _set_breaker(
    provider,
    *,
    state="CLOSED",
    failures=0,
    last_success_time=0.0,
    last_failure_time=0.0,
):
    """Set one provider's shared breaker to an explicit observed state."""
    breaker = get_circuit_breaker(provider)
    breaker.state = state
    breaker.failure_count = failures
    breaker.last_success_time = last_success_time
    breaker.last_failure_time = last_failure_time


def _open_provider_breakers():
    """Leave both providers observably failing, with no recent success."""
    for provider in ("openai", "perplexity"):
        _set_breaker(
            provider,
            state="OPEN",
            failures=5,
            last_failure_time=time.monotonic(),
        )


def test_health_reports_failing_providers_instead_of_healthy():
    """/health must not claim healthy while provider breakers are open."""
    _open_provider_breakers()
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "unhealthy", body
    assert set(body["failing_providers"]) == {"openai", "perplexity"}, body
    assert body["providers"]["openai"]["state"] == "OPEN", body
    assert body["providers"]["perplexity"]["state"] == "OPEN", body


def test_readiness_reports_not_ready_when_providers_are_failing():
    """/health/ready must reflect provider failures, not just client identity."""
    _open_provider_breakers()
    response = request_health(create_health_app(_deps()), "/health/ready")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "not_ready", body
    assert set(body["failing_providers"]) == {"openai", "perplexity"}, body


# The previous version of this test asserted that a closed breaker whose last
# success was an hour old was degraded. That made every quiet bot report itself
# broken: absence of traffic is not evidence of failure. A stale success is
# still reported through last_success_age_seconds and last_success_stale, but
# only an open/half-open breaker or a failure after the last success decides
# health. The pair below states the rule in both directions so this is not a
# lowered floor.
def test_old_success_without_failures_is_healthy():
    """A closed breaker with an old success and no failures is healthy."""
    _set_breaker("openai", last_success_time=time.monotonic() - 3600)
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "healthy", body
    assert body["failing_providers"] == [], body
    assert body["providers"]["openai"]["status"] == "healthy", body
    assert body["providers"]["openai"]["last_success_age_seconds"] >= 3599, body
    assert body["providers"]["openai"]["last_success_stale"] is True, body
    assert body["services"]["openai"] == "configured", body
    assert body["services"]["openai_configured"] is True, body
    assert body["providers"]["openai"]["configured"] is True, body


def test_failure_after_success_is_degraded():
    """A failure after the last success is evidence of current ill health."""
    now = time.monotonic()
    _set_breaker(
        "openai",
        failures=1,
        last_success_time=now - 3600,
        last_failure_time=now,
    )
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] == "degraded", body
    assert body["failing_providers"] == ["openai"], body
    assert body["providers"]["openai"]["status"] == "degraded", body


def test_never_called_provider_is_healthy_and_not_failing():
    """A provider that has never been called is idle, not broken."""
    _set_breaker("openai")
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "healthy", body
    assert body["failing_providers"] == [], body
    provider = body["providers"]["openai"]
    assert provider["status"] == "healthy", body
    assert provider["last_success_age_seconds"] is None, body
    assert provider["last_success_stale"] is False, body


@pytest.mark.parametrize(
    ("breaker_state", "provider_status"),
    [("OPEN", "unhealthy"), ("HALF_OPEN", "degraded")],
)
def test_open_and_half_open_breakers_still_fail_health(breaker_state, provider_status):
    """An open or probing breaker must never report healthy."""
    _set_breaker(
        "openai",
        state=breaker_state,
        failures=5,
        last_failure_time=time.monotonic(),
    )
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["status"] != "healthy", body
    assert body["failing_providers"] == ["openai"], body
    assert body["providers"]["openai"]["status"] == provider_status, body


@pytest.mark.parametrize(
    ("failure_age", "expected_code", "expected_provider_status"),
    [(59.0, 503, "unhealthy"), (61.0, 200, "healthy")],
)
def test_open_breaker_past_its_timeout_is_recovering(
    failure_age,
    expected_code,
    expected_provider_status,
):
    """An idle open breaker is not unhealthy once its timeout has elapsed."""
    _set_breaker(
        "openai",
        state="OPEN",
        failures=5,
        last_failure_time=100.0,
    )
    with patch("src.health_server.time.monotonic", return_value=100.0 + failure_age):
        response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == expected_code, body
    assert body["providers"]["openai"]["status"] == expected_provider_status, body
    if expected_code == 200:
        assert "openai" not in body["failing_providers"], body


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
        response = request_health(create_health_app(_deps(pool_manager=manager)), "/health")

        body = response.json()
        assert body["services"]["pool"]["openai"]["http2_enabled"] is True, body
    finally:
        asyncio.run(manager.close_all())


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), 0.0])
def test_non_finite_or_zero_latency_does_not_cause_500(latency):
    """Invalid latency values are reported as null rather than crashing JSON."""
    response = request_health(create_health_app(_deps(latency=latency)), "/health")

    assert response.status_code != 500, response.text
    body = response.json()
    assert body["services"]["latency_ms"] is None, body


def test_health_json_keeps_every_documented_key():
    """New truthfulness fields must not remove the existing contract."""
    response = request_health(create_health_app(_deps(pool_manager=_FakePoolManager())), "/health")

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


def test_client_errors_keep_provider_health_healthy():
    """A user-caused 400 must not degrade the provider or make /health 503."""
    import openai

    from src.error_handling import get_circuit_breaker

    async def exercise_breaker():
        breaker = get_circuit_breaker("openai")
        error = openai.BadRequestError(
            "invalid request",
            response=SimpleNamespace(status_code=400, headers={}, request=SimpleNamespace()),
            body=None,
        )

        async def rejected():
            raise error

        for _ in range(5):
            with pytest.raises(openai.BadRequestError):
                await breaker.call(rejected)

    asyncio.run(exercise_breaker())
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "healthy", body
    assert body["providers"]["openai"]["status"] == "healthy", body
    assert body["providers"]["openai"]["consecutive_failures"] == 0, body


def test_invalid_model_400_makes_provider_health_degraded():
    """A retired Perplexity model must show on /health instead of looking neutral."""
    import httpx
    import openai

    from src.error_handling import get_circuit_breaker

    async def exercise_breaker():
        breaker = get_circuit_breaker("perplexity")
        request = httpx.Request("POST", "https://api.perplexity.ai/v1/responses")
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "model is not supported", "type": "invalid_model"}},
        )
        error = openai.BadRequestError(
            "model is not supported",
            response=response,
            body=response.json(),
        )

        async def rejected():
            raise error

        with pytest.raises(openai.BadRequestError):
            await breaker.call(rejected)

    asyncio.run(exercise_breaker())
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["failing_providers"] == ["perplexity"], body
    assert body["providers"]["perplexity"]["status"] == "degraded", body
    assert body["providers"]["perplexity"]["consecutive_failures"] == 1, body


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        ("AuthenticationError", 401),
        ("PermissionDeniedError", 403),
        ("NotFoundError", 404),
    ],
)
def test_configuration_errors_make_provider_health_degraded(error_type, status_code):
    """A revoked key or retired model must not keep /health green."""
    import httpx
    import openai

    from src.error_handling import get_circuit_breaker

    async def exercise_breaker():
        breaker = get_circuit_breaker("openai")
        request = httpx.Request("POST", "https://api.example/v1/chat/completions")
        response = httpx.Response(
            status_code,
            request=request,
            json={"error": {"message": "request rejected", "type": "invalid_request_error"}},
        )
        error_class = getattr(openai, error_type)
        error = error_class("request rejected", response=response, body=response.json())

        async def rejected():
            raise error

        with pytest.raises(error_class):
            await breaker.call(rejected)

    asyncio.run(exercise_breaker())
    response = request_health(create_health_app(_deps()), "/health")

    body = response.json()
    assert response.status_code == 503, body
    assert body["failing_providers"] == ["openai"], body
    assert body["providers"]["openai"]["status"] == "degraded", body
    assert body["providers"]["openai"]["consecutive_failures"] == 1, body


def test_gateway_disconnect_is_not_ready_even_when_is_ready_stays_true():
    """A gateway outage must be reported even though discord.py is_ready sticks."""
    deps = _deps(connected=True)
    deps["bot"].discordian_gateway_connected = False
    health = request_health(create_health_app(deps), "/health")
    ready = request_health(create_health_app(deps), "/health/ready")

    health_body = health.json()
    assert health.status_code == 503, health_body
    assert health_body["status"] == "unhealthy", health_body
    assert health_body["services"]["discord"] == "disconnected", health_body

    ready_body = ready.json()
    assert ready.status_code == 503, ready_body
    assert ready_body["status"] == "not_ready", ready_body
