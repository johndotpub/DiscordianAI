"""Replay helpers shared by the golden test and the regeneration script.

The helpers only use the in-memory fakes and ``deps`` shape already used by the
existing Discord tests.  No network or real Discord objects are involved.
"""

import asyncio
from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from src.discord_embeds import citation_embed_formatter
from src.message_splitter import send_split_message, send_split_message_with_embed
from src.perplexity_processing import (
    _build_api_params,
    _normalize_citation_text,
    format_citations_for_discord,
)
from tests.golden_cases import (
    CASES_BY_SURFACE,
    SURFACE_API_PARAMS,
    SURFACE_CITATION_EMBED,
    SURFACE_FORMAT_CITATIONS,
    SURFACE_SEND_SPLIT,
    SURFACE_SEND_SPLIT_EMBED,
    SURFACES,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"

SURFACE_FILES = {
    SURFACE_SEND_SPLIT: "send_split_message.json",
    SURFACE_SEND_SPLIT_EMBED: "send_split_message_with_embed.json",
    SURFACE_FORMAT_CITATIONS: "format_citations_for_discord.json",
    SURFACE_CITATION_EMBED: "citation_embed_formatter.json",
    SURFACE_API_PARAMS: "build_api_params.json",
}

USER_ID = 987654321
USER_NAME = "test_user"
USER_MENTION = "<@987654321>"
CHANNEL_ID = 123456789


@dataclass
class Replay:
    """Serialised result plus the raw captured calls for invariant checks."""

    result: Any
    calls: list[dict[str, Any]]
    original_message: Any = None


class _Recorder:
    """Capture send/reply calls in the exact order they happen."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append({"method": "send", "args": args, "kwargs": kwargs})

    async def reply(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append({"method": "reply", "args": args, "kwargs": kwargs})


def _make_channel(recorder: _Recorder) -> AsyncMock:
    channel = AsyncMock()
    channel.send = recorder.send
    channel.id = CHANNEL_ID
    channel.name = "general"
    return channel


def _make_original_message(recorder: _Recorder) -> MagicMock:
    author = MagicMock()
    author.id = USER_ID
    author.name = USER_NAME
    author.mention = USER_MENTION

    original_message = MagicMock(spec=discord.Message)
    original_message.author = author
    original_message.reply = recorder.reply
    original_message.content = "Hello, bot!"
    return original_message


def _serialize_allowed_mentions(value: discord.AllowedMentions) -> dict[str, Any]:
    users = [
        {"id": getattr(user, "id", None), "name": getattr(user, "name", None)}
        for user in (value.users or [])
    ]
    roles: Any = value.roles
    if isinstance(roles, list):
        roles = [getattr(role, "id", role) for role in roles]
    else:
        roles = bool(roles)
    return {
        "users": users,
        "roles": roles,
        "everyone": bool(value.everyone),
        "replied_user": bool(value.replied_user),
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, discord.AllowedMentions):
        return _serialize_allowed_mentions(value)
    if isinstance(value, discord.Embed):
        return value.to_dict()
    return value


def _serialize_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized = []
    for call in calls:
        content = call["args"][0] if call["args"] else None
        serialized.append(
            {
                "method": call["method"],
                "content": content,
                "kwargs": {key: _serialize_value(value) for key, value in call["kwargs"].items()},
            }
        )
    return serialized


def _make_embed(spec: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(color=spec["color"])
    if spec.get("title"):
        embed.title = spec["title"]
    embed.description = spec.get("description", "")
    if spec.get("footer"):
        embed.set_footer(text=spec["footer"])
    return embed


async def replay_case(case: dict[str, Any]) -> Replay:
    """Run one case against the real source functions."""
    recorder = _Recorder()
    channel = _make_channel(recorder)
    inputs = case["inputs"]
    original_message = _make_original_message(recorder) if inputs.get("original_message") else None
    deps = {"logger": MagicMock()}
    surface = case["surface"]

    if surface == SURFACE_SEND_SPLIT:
        await send_split_message(
            channel,
            inputs["message"],
            deps,
            suppress_embeds=inputs["suppress_embeds"],
            original_message=original_message,
            mention_prefix=inputs["mention_prefix"],
            _recursion_depth=inputs["recursion_depth"],
        )
        result = _serialize_calls(recorder.calls)
    elif surface == SURFACE_SEND_SPLIT_EMBED:
        embed = _make_embed(inputs["embed"])
        await send_split_message_with_embed(
            channel,
            inputs["message"],
            deps,
            embed,
            inputs["citations"],
            original_message=original_message,
            mention_prefix=inputs["mention_prefix"],
            _recursion_depth=inputs["recursion_depth"],
        )
        result = _serialize_calls(recorder.calls)
    elif surface == SURFACE_FORMAT_CITATIONS:
        function_name = inputs["function"]
        if function_name == "format_citations_for_discord":
            result = format_citations_for_discord(
                inputs["text"],
                inputs["citations"],
                linkify=inputs["linkify"],
            )
        else:
            result = _normalize_citation_text(inputs["text"], inputs["citations"])
    elif surface == SURFACE_CITATION_EMBED:
        embed, metadata = citation_embed_formatter.create_citation_embed(
            inputs["content"],
            inputs["citations"],
            title=inputs["title"],
            footer_text=inputs["footer_text"],
        )
        result = {
            "embed": embed.to_dict(),
            "metadata": metadata,
            "title": embed.title,
            "description": embed.description,
            "colour": None if embed.color is None else int(embed.color),
            "footer": embed.footer.text if embed.footer else None,
            "field_count": len(embed.fields),
        }
    elif surface == SURFACE_API_PARAMS:
        result = _build_api_params(
            inputs["model"],
            inputs["system"],
            inputs["user_msg"],
            inputs["tokens"],
            history=inputs.get("history"),
        )
    else:  # pragma: no cover - guarded by the fixed surface list
        msg = f"Unknown golden surface: {surface}"
        raise ValueError(msg)

    return Replay(result=result, calls=recorder.calls, original_message=original_message)


async def run_all() -> dict[str, dict[str, Any]]:
    """Replay every case and return results grouped by surface."""
    results: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        surface_results: dict[str, Any] = {}
        for case in CASES_BY_SURFACE[surface]:
            replay = await replay_case(case)
            surface_results[case["id"]] = replay.result
        results[surface] = surface_results
    return results


def run_all_sync() -> dict[str, dict[str, Any]]:
    """Synchronous wrapper used by the regeneration script."""
    return asyncio.run(run_all())


def fixture_path(surface: str) -> Path:
    """Return the fixture path for ``surface``."""
    return FIXTURE_DIR / SURFACE_FILES[surface]


@cache
def load_fixture(surface: str) -> dict[str, Any]:
    """Load and cache one surface fixture from disk."""
    with fixture_path(surface).open(encoding="utf-8") as handle:
        return json.load(handle)
