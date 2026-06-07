"""Tests for the BotDependencies dataclass."""

from unittest.mock import MagicMock

import pytest

from src.dependencies import BotDependencies


@pytest.fixture
def deps():
    """Create a minimal BotDependencies instance."""
    return BotDependencies(
        bot=MagicMock(),
        logger=MagicMock(),
        config={"GPT_MODEL": "gpt-5-mini"},
        allowed_channels=["general"],
    )


def test_dict_access(deps):
    """BotDependencies supports dict-style bracket access."""
    assert deps["logger"] is deps.logger
    assert deps["GPT_MODEL"] == "gpt-5-mini"


def test_contains(deps):
    """BotDependencies supports ``key in deps``."""
    assert "logger" in deps
    assert "nonexistent" not in deps


def test_get(deps):
    """BotDependencies supports ``deps.get(key, default)``."""
    assert deps.get("logger") is deps.logger
    assert deps.get("nonexistent") is None
    assert deps.get("nonexistent", 42) == 42


def test_to_dict_roundtrip(deps):
    """to_dict() produces a valid dict with all keys."""
    d = deps.to_dict()
    assert isinstance(d, dict)
    assert "logger" in d
    assert "GPT_MODEL" in d
    assert d["ALLOWED_CHANNELS"] == ["general"]


def test_attribute_access(deps):
    """BotDependencies supports attribute access."""
    assert deps.gpt_model == "gpt-5-mini"
    assert deps.allowed_channels == ["general"]


def test_health_task_default_none():
    """health_task defaults to None."""
    deps = BotDependencies(bot=MagicMock(), logger=MagicMock(), config={})
    assert deps.health_task is None
