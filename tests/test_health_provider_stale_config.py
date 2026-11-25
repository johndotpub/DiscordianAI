"""Regression tests for HEALTH_PROVIDER_STALE_SECONDS configuration wiring."""

from unittest.mock import patch

from src.config import load_config
from src.health_server import create_health_app
from tests.helpers import FakeBreaker, health_deps, request_health

_Breaker = FakeBreaker


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

    deps = health_deps(
        guilds=[],
        config=config,
        breakers={
            "openai": _Breaker(9_900.0),
            "perplexity": _Breaker(9_900.0),
        },
    )

    with patch("src.health_server.time.monotonic", return_value=10_000.0):
        response = request_health(create_health_app(deps), "/health")

    body = response.json()
    assert response.status_code == 200, body
    assert body["failing_providers"] == [], body
    assert body["providers"]["openai"]["status"] == "healthy"
    assert body["providers"]["perplexity"]["status"] == "healthy"
    assert body["providers"]["openai"]["last_success_stale"] is True
    assert body["providers"]["perplexity"]["last_success_stale"] is True
