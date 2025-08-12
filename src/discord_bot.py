"""Discord bot utilities and helper functions.

This module provides utility functions for Discord-specific functionality
including activity status management and bot presence configuration.
"""

# Third-party imports
import discord


def set_activity_status(activity_type: str, activity_status: str) -> discord.Activity:
    """Create a Discord Activity object with the specified type and status.

    Converts string activity types to Discord ActivityType enums and creates
    an appropriate Activity object for bot presence display.

    Args:
        activity_type (str): The type of activity to display. Valid values:
                           'playing', 'streaming', 'listening', 'watching',
                           'custom', 'competing'
        activity_status (str): The status message to display with the activity

    Returns:
        discord.Activity: Configured activity object for bot presence

    Examples:
        >>> activity = set_activity_status("watching", "for messages")
        >>> # Bot will show "Watching for messages"

        >>> activity = set_activity_status("playing", "chess")
        >>> # Bot will show "Playing chess"

    Note:
        If an invalid activity_type is provided, defaults to 'listening'.
        This ensures the bot always has a valid activity status.
    """
    # Map string activity types to Discord enums
    activity_types = {
        "playing": discord.ActivityType.playing,
        "streaming": discord.ActivityType.streaming,
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "custom": discord.ActivityType.custom,
        "competing": discord.ActivityType.competing,
    }

    # Get the activity type, defaulting to 'listening' if invalid
    selected_type = activity_types.get(activity_type.lower(), discord.ActivityType.listening)

    return discord.Activity(
        type=selected_type,
        name=activity_status,
    )
