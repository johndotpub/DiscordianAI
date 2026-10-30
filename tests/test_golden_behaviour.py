"""Golden-behaviour regression tests for DiscordianAI.

Every case is replayed against the real source functions and compared with the
recorded fixture.  A fixture diff in a future PR is therefore a deliberate,
reviewable statement that user-visible behaviour changed.
"""

import asyncio
import json

import discord
import pytest

from tests.golden_cases import (
    ALL_CASES,
    SURFACE_CITATION_EMBED,
    SURFACE_SEND_SPLIT,
    SURFACE_SEND_SPLIT_EMBED,
)
from tests.golden_runner import load_fixture, replay_case


def _expected(case: dict) -> object:
    fixture = load_fixture(case["surface"])
    assert fixture["surface"] == case["surface"]
    return fixture["cases"][case["id"]]


def _assert_discord_call_invariants(replay) -> None:
    for call in replay.calls:
        kwargs = call["kwargs"]
        assert kwargs.get("mention_author", False) is False

        if call["method"] == "reply":
            assert replay.original_message is not None
            allowed_mentions = kwargs["allowed_mentions"]
            assert allowed_mentions.users == [replay.original_message.author]
            assert allowed_mentions.replied_user is False
        else:
            assert call["method"] == "send"
            assert "mention_author" not in kwargs
            allowed_mentions = kwargs["allowed_mentions"]
            assert isinstance(allowed_mentions, discord.AllowedMentions)
            assert allowed_mentions.users == []
            assert allowed_mentions.roles == []
            assert allowed_mentions.everyone is False
            parse = allowed_mentions.to_dict()["parse"]
            assert "everyone" not in parse
            assert "roles" not in parse


@pytest.mark.parametrize("case", ALL_CASES, ids=[case["id"] for case in ALL_CASES])
def test_golden_behaviour(case: dict) -> None:
    """Replay one recorded case and fail on any observable drift."""
    replay = asyncio.run(replay_case(case))
    expected = _expected(case)

    assert replay.result == expected

    if case["surface"] in (SURFACE_SEND_SPLIT, SURFACE_SEND_SPLIT_EMBED):
        assert [call["content"] for call in replay.result] == [
            call["content"] for call in expected
        ]
        _assert_discord_call_invariants(replay)

    if case["surface"] == SURFACE_CITATION_EMBED:
        assert replay.result["title"] == expected["title"]
        assert replay.result["description"] == expected["description"]
        assert replay.result["colour"] == expected["colour"]
        assert replay.result["footer"] == expected["footer"]
        assert replay.result["field_count"] == expected["field_count"] == 0
        assert json.dumps(replay.result["embed"])
        assert json.dumps(replay.result["metadata"])
