"""Edge coverage for health checks: missing data, bounds, and isolation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.config import DEFAULT_PERPLEXITY_MODEL
from src.health_checks import APIHealthMonitor


@pytest.mark.asyncio
async def test_ready_discord_bot_without_latency_reports_healthy():
    """A bot that never reported latency is reported healthy with a null latency."""
    monitor = APIHealthMonitor()
    bot = SimpleNamespace(is_ready=lambda: True, guilds=[])

    result = await monitor.check_discord_health(bot)

    assert result.status == "healthy"
    assert result.details["latency_ms"] is None


@pytest.mark.asyncio
async def test_empty_model_listing_is_unhealthy():
    """An empty provider model list is an invalid response, not a healthy one."""
    monitor = APIHealthMonitor()
    client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[])),
        )
    )

    result = await monitor.check_openai_health(client, {})

    assert result.status == "unhealthy"
    assert "provider returned no models" in result.error


def test_unknown_dynamic_health_check_name_raises_attribute_error():
    """An unknown check name reports the missing attribute instead of guessing."""
    monitor = APIHealthMonitor()

    with pytest.raises(AttributeError, match="check_missing_health"):
        _ = monitor.check_missing_health


class _ExplodingOpenAIMonitor(APIHealthMonitor):
    """Health monitor whose OpenAI check cannot complete."""

    async def check_openai_health(self, *_args, **_kwargs):
        msg = "openai checker exploded"
        raise RuntimeError(msg)


@pytest.mark.asyncio
async def test_one_failing_health_check_does_not_hide_the_others(caplog):
    """A checker that raises is logged while the remaining providers still run."""
    monitor = _ExplodingOpenAIMonitor()
    perplexity_client = SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(
                return_value=SimpleNamespace(
                    data=[SimpleNamespace(id=DEFAULT_PERPLEXITY_MODEL)],
                )
            )
        )
    )

    with caplog.at_level("ERROR", logger="src.health_checks"):
        results = await monitor.run_all_health_checks(
            {"openai": object(), "perplexity": perplexity_client},
            {},
        )

    assert set(results) == {"openai", "perplexity"}
    assert results["openai"].status == "unhealthy"
    assert results["openai"].error == "check raised RuntimeError"
    assert results["openai"].details["error_type"] == "RuntimeError"
    assert results["perplexity"].status == "healthy"
    assert any(record.getMessage() == "Failed to check OpenAI health" for record in caplog.records)
    assert "openai checker exploded" in caplog.text
