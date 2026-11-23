"""Shared text primitives used by routing cues and follow-up detection."""

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
"""The single token pattern used by cue extraction and follow-up matching."""
