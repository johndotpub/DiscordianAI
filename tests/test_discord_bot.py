import pytest
from src.discord_bot import set_activity_status
import discord


@pytest.mark.parametrize(
    "activity_type",
    ["playing", "streaming", "listening", "watching", "custom", "competing", "invalid"],
)
def test_set_activity_status_all_types(activity_type):
    activity = set_activity_status(activity_type, "Test")
    assert isinstance(activity, discord.Activity)
    assert hasattr(activity, "type")
    assert hasattr(activity, "name")
