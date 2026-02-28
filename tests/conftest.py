"""Pytest configuration helpers for DiscordianAI tests."""

import warnings

# Discord.py still imports the stdlib audioop module, which raises a global
# DeprecationWarning on Python 3.12+ when tests enable ``-W error``. Keep the
# suite green by filtering that specific upstream warning while leaving the rest
# of the strict warning policy intact.
warnings.filterwarnings(
    "ignore",
    message="'audioop' is deprecated and slated for removal in Python 3.13",
    category=DeprecationWarning,
    module=r"discord\.player",
)
