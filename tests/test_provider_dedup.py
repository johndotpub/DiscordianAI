"""Regression tests for the table-driven provider implementations."""

import ast
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src import health_checks
from src.health_checks import APIHealthMonitor


def _models_client(model_ids, error=None):
    client = Mock()
    if error is not None:
        client.models.list = AsyncMock(side_effect=RuntimeError(error))
        return client

    response = Mock()
    response.data = [Mock(id=model_id) for model_id in model_ids]
    client.models.list = AsyncMock(return_value=response)
    return client


def _discord_client(latency_ms=100.0, error=None):
    client = Mock()
    if error is not None:
        client.is_ready.side_effect = RuntimeError(error)
        return client

    client.is_ready.return_value = True
    client.latency = latency_ms / 1000
    client.guilds = []
    client.user = Mock(id=1)
    return client


async def _run_check(monitor, service, client, config):
    if service == "openai":
        return await monitor.check_openai_health(client, config)
    if service == "perplexity":
        return await monitor.check_perplexity_health(client, config)
    return await monitor.check_discord_health(client)


@pytest.mark.asyncio
async def test_provider_result_shapes_match():
    """Every provider reports the same failure detail keys and value types."""
    monitor = APIHealthMonitor()
    clients = {
        "openai": _models_client([], error="openai down"),
        "perplexity": _models_client([], error="perplexity down"),
        "discord": _discord_client(error="discord down"),
    }
    results = {
        service: await _run_check(monitor, service, client, {})
        for service, client in clients.items()
    }

    key_sets = {service: set(result.details) for service, result in results.items()}
    assert key_sets["openai"] == key_sets["perplexity"] == key_sets["discord"]

    for key in key_sets["openai"]:
        value_types = {service: type(result.details[key]) for service, result in results.items()}
        assert len(set(value_types.values())) == 1, value_types


@pytest.mark.asyncio
async def test_synthetic_provider_works_from_one_table_row(monkeypatch):
    """A new provider row is enough to produce a normal result."""
    specs = health_checks.PROVIDER_HEALTH_SPECS
    assert {"openai", "perplexity", "discord"} <= set(specs)
    assert all(key == spec.service for key, spec in specs.items())

    synthetic = replace(
        specs["openai"],
        service="synthetic",
        display_name="Synthetic",
        client_key="synthetic",
        model_key="SYNTHETIC_MODEL",
        default_model="synthetic-default",
        allowed_models=("synthetic-default",),
        model_validator=None,
        degraded_threshold_ms=10,
        unhealthy_threshold_ms=100,
    )
    monkeypatch.setitem(specs, "synthetic", synthetic)

    monitor = APIHealthMonitor()
    result = await monitor.check_provider_health(
        "synthetic",
        _models_client(["synthetic-default"]),
        {},
    )
    assert result.service == "synthetic"
    assert result.status == "healthy"
    assert result.details["model"] == "synthetic-default"

    openai_result = await monitor.check_provider_health(
        "openai",
        _models_client(["gpt-5-mini"]),
        {"GPT_MODEL": "gpt-5-mini"},
    )
    assert set(result.details) == set(openai_result.details)
    assert {key: type(value) for key, value in result.details.items()} == {
        key: type(value) for key, value in openai_result.details.items()
    }

    times = iter([0.0, 0.05])
    monkeypatch.setattr(health_checks.time, "time", lambda: next(times))
    slow_result = await monitor.check_provider_health(
        "synthetic",
        _models_client(["synthetic-default"]),
        {},
    )
    assert slow_result.status == "degraded"


def test_only_one_provider_specific_health_implementation():
    """Provider-specific health code must not be copied per provider."""
    tree = ast.parse(Path(health_checks.__file__).read_text(encoding="utf-8"))
    provider_names = ("openai", "perplexity")
    provider_functions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(provider in node.name.lower() for provider in provider_names)
    ]

    assert len(provider_functions) < 2, provider_functions
    assert hasattr(health_checks, "PROVIDER_HEALTH_SPECS")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "elapsed_ms", "expected"),
    [
        ("openai", 1.0, "healthy"),
        ("openai", 6000.0, "degraded"),
        ("openai", 11000.0, "unhealthy"),
        ("perplexity", 1.0, "healthy"),
        ("perplexity", 9000.0, "degraded"),
        ("perplexity", 16000.0, "unhealthy"),
        ("discord", 100.0, "healthy"),
        ("discord", 600.0, "degraded"),
        ("discord", 1100.0, "unhealthy"),
    ],
)
async def test_existing_status_classification_is_preserved(
    monkeypatch, service, elapsed_ms, expected
):
    """Healthy, degraded, and unhealthy thresholds keep their old results."""
    monitor = APIHealthMonitor()
    if service == "discord":
        client = _discord_client(latency_ms=elapsed_ms)
        result = await _run_check(monitor, service, client, {})
    else:
        times = iter([0.0, elapsed_ms / 1000])
        monkeypatch.setattr(health_checks.time, "time", lambda: next(times))
        client = _models_client(["gpt-5-mini"] if service == "openai" else ["sonar-pro"])
        config = (
            {"GPT_MODEL": "gpt-5-mini"}
            if service == "openai"
            else {"PERPLEXITY_MODEL": "sonar-pro"}
        )
        result = await _run_check(monitor, service, client, config)

    assert result.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["openai", "perplexity", "discord"])
async def test_raising_clients_stay_unhealthy(service):
    """Exceptions still produce an unhealthy result for every provider."""
    monitor = APIHealthMonitor()
    if service == "discord":
        client = _discord_client(error="discord down")
    else:
        client = _models_client([], error=f"{service} down")

    result = await _run_check(monitor, service, client, {})

    assert result.status == "unhealthy"
    assert result.error
