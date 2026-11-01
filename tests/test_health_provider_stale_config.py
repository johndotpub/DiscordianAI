"""Regression tests for HEALTH_PROVIDER_STALE_SECONDS configuration wiring."""

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from src.config import load_config
from src.health_server import create_health_app


class _Breaker:
    """Minimal breaker snapshot provider for the health endpoint."""

    def __init__(self, last_success_time: float) -> None:
        self._last_success_time = last_success_time

    def snapshot(self) -> dict:
        """Return a closed breaker with an old successful call."""
        return {
            "state": "CLOSED",
            "consecutive_failures": 0,
            "last_failure_time": 0.0,
            "last_success_time": self._last_success_time,
        }


def test_provider_stale_seconds_from_config_sets_informational_flag(tmp_path, monkeypatch):
    """A configured 45-second staleness threshold marks the success as stale.

    Staleness is reported for operators but does not degrade health; a closed
    breaker with no failures after its last success is still healthy.
    """
    monkeypatch.delenv("HEALTH_PROVIDER_STALE_SECONDS", raising=False)
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        "[Health]\nHEALTH_PROVIDER_STALE_SECONDS=45\n",
        encoding="utf-8",
    )
    config = load_config(str(config_path))
    assert config["HEALTH_PROVIDER_STALE_SECONDS"] == 45

    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.guilds = []
    bot.latency = 0.05
    deps = {
        "bot": bot,
        "client": MagicMock(),
        "perplexity_client": MagicMock(),
        "config": config,
        "circuit_breakers": {
            "openai": _Breaker(9_900.0),
            "perplexity": _Breaker(9_900.0),
        },
    }

    with patch("src.health_server.time.monotonic", return_value=10_000.0):
        with TestClient(create_health_app(deps)) as client:
            response = client.get("/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["failing_providers"] == [], body
    assert body["providers"]["openai"]["status"] == "healthy"
    assert body["providers"]["perplexity"]["status"] == "healthy"
    assert body["providers"]["openai"]["last_success_stale"] is True
    assert body["providers"]["perplexity"]["last_success_stale"] is True
