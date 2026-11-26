"""Guard against configuration and provider settings leaking in from the host shell."""

import os

import pytest

from tests.helpers import config_env_keys

PROVIDER_PREFIXES = ("OLLAMA_", "OPENAI_", "PERPLEXITY_", "ROUTER_")
SEEDED_KEYS = ("GPT_MODEL", "WEB_TOOLS", "RATE_LIMIT", "HEALTH_PORT", "LOG_LEVEL")
_SENTINEL = "sentinel-from-host-shell"


@pytest.fixture
def seeded_environment(monkeypatch):
    """Seed config keys before the autouse scrub fixture runs."""
    for key in SEEDED_KEYS:
        monkeypatch.setenv(key, _SENTINEL)
    return SEEDED_KEYS


def test_provider_and_router_variables_are_removed_before_each_test():
    """No test may depend on a provider key that happens to be exported."""
    inherited = sorted(
        name
        for name in os.environ
        if name.startswith(PROVIDER_PREFIXES) or name == "DISCORD_TOKEN"
    )

    assert not inherited, f"host variables reached a test: {inherited}"


def test_seeded_config_keys_are_removed_before_each_test(seeded_environment):
    """The shared scrub covers config keys outside the provider prefixes."""
    remaining = sorted(name for name in seeded_environment if name in os.environ)

    assert not remaining, f"host variables reached a test: {remaining}"


def test_seeded_keys_are_read_by_the_config_loader():
    """The sentinels exercise the config loader's own key set."""
    assert set(SEEDED_KEYS) <= config_env_keys()
