"""Shared text primitives used by routing cues and follow-up detection."""

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
"""The single token pattern used by cue extraction and follow-up matching."""

APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u2032": "'",
    }
)
"""Typographic apostrophes mapped to the ASCII apostrophe in one place."""


def normalise_apostrophes(text: str) -> str:
    """Replace typographic apostrophes with the ASCII apostrophe.

    The replacement is one character for one character, so offsets into the
    returned text remain valid positions in the original.
    """
    return text.translate(APOSTROPHES)
