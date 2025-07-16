# Third-party imports
import discord


def set_activity_status(activity_type: str, activity_status: str) -> discord.Activity:
    """
    Return discord.Activity object with specified activity type and status.

    Args:
        activity_type (str): The type of activity.
        activity_status (str): The status of the activity.

    Returns:
        discord.Activity: The activity object.
    """
    activity_types = {
        "playing": discord.ActivityType.playing,
        "streaming": discord.ActivityType.streaming,
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "custom": discord.ActivityType.custom,
        "competing": discord.ActivityType.competing,
    }
    return discord.Activity(
        type=activity_types.get(activity_type, discord.ActivityType.listening),
        name=activity_status,
    )
