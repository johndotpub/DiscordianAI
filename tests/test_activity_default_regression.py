"""Regression tests for the restored listening activity default."""

import discord

from src.config import DEFAULT_ACTIVITY_TYPE, DISCORD_ACTIVITY_TYPES, load_config
from src.discord_bot import set_activity_status


def test_activity_type_absent_from_config_falls_back_to_listening(monkeypatch):
    """A deployment without ACTIVITY_TYPE keeps the pre-remediation default."""
    monkeypatch.delenv("ACTIVITY_TYPE", raising=False)

    config = load_config()

    assert DEFAULT_ACTIVITY_TYPE == "listening"
    assert config["ACTIVITY_TYPE"] == "listening"


def test_invalid_activity_type_falls_back_to_listening():
    """Unknown activity values still fall back to the configured default."""
    assert "teleporting" not in DISCORD_ACTIVITY_TYPES

    activity = set_activity_status("teleporting", "Humans")

    assert activity.type is discord.ActivityType.listening
