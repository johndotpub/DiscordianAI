"""Long answers must be delivered completely instead of hitting a depth guard."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.message_splitter import send_split_message, send_split_message_with_embed

MENTION_PREFIX = "<@42> "


class RecordingChannel:
    """Capture plain channel sends without a real Discord connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send(self, content: str, **kwargs) -> None:
        self.calls.append((content, kwargs))


def _original_message() -> SimpleNamespace:
    author = SimpleNamespace(id=42, mention="<@42>", bot=False)
    original = SimpleNamespace(author=author)
    original.reply = AsyncMock()
    return original


def _reply_texts(original: SimpleNamespace) -> list[str]:
    return [call.args[0] for call in original.reply.call_args_list]


def _unlink_embed_citations(text: str) -> str:
    return re.sub(r"\[\[(\d+)\]\]\([^)]+\)", r"[\1]", text)


def _rendered_embed_texts(calls) -> list[str]:
    rendered: list[str] = []
    for call in calls:
        rendered.append(call.args[0])
        embed = call.kwargs.get("embed")
        if embed is not None:
            rendered.append(_unlink_embed_citations(embed.description))
    return rendered


@pytest.mark.asyncio
async def test_21111_char_body_with_mention_prefix_is_delivered_in_full():
    channel = RecordingChannel()
    original = _original_message()
    body = "A" * 21111

    await send_split_message(
        channel,
        body,
        {"logger": MagicMock()},
        original_message=original,
        mention_prefix=MENTION_PREFIX,
    )

    chunks = _reply_texts(original)
    assert len(chunks) == 12
    assert "".join(chunks) == f"{MENTION_PREFIX}{body}"
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert not any("truncated" in chunk.lower() for chunk in chunks)


@pytest.mark.asyncio
async def test_60000_char_body_is_delivered_with_expected_chunk_count():
    channel = RecordingChannel()
    body = "B" * 60000

    await send_split_message(channel, body, {"logger": MagicMock()})

    chunks = [content for content, _ in channel.calls]
    assert len(chunks) == 32
    assert "".join(chunks) == body
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert not any("truncated" in chunk.lower() for chunk in chunks)


@pytest.mark.asyncio
async def test_long_cited_answer_with_embed_arrives_complete():
    channel = RecordingChannel()
    original = _original_message()
    body = "[1]" + ("A" * 59994) + "[2]"
    citations = {
        "1": "https://example.com/source/1",
        "2": "https://example.com/source/2",
    }
    embed = discord.Embed(description="placeholder")

    await send_split_message_with_embed(
        channel,
        body,
        {"logger": MagicMock()},
        embed,
        citations,
        original_message=original,
        mention_prefix=MENTION_PREFIX,
    )

    calls = original.reply.call_args_list
    assert calls[0].kwargs["embed"] is embed
    rendered = _rendered_embed_texts(calls)
    assert "".join(rendered) == f"{MENTION_PREFIX}{body}"
    assert not any("truncated" in text.lower() for text in rendered)


@pytest.mark.asyncio
async def test_indivisible_code_fence_is_truncated_with_a_notice():
    channel = RecordingChannel()
    fence = "```\n" + ("A" * 4992) + "\n```"
    assert len(fence) == 5000

    await send_split_message(channel, fence, {"logger": MagicMock()})

    chunks = [content for content, _ in channel.calls]
    assert len(chunks) == 1
    assert len(chunks[0]) <= 2000
    assert "truncated" in chunks[0].lower()


@pytest.mark.asyncio
async def test_chunk_cap_logs_an_error_and_stops_delivery():
    channel = RecordingChannel()
    logger = MagicMock()
    body = "C" * 200000

    await send_split_message(channel, body, {"logger": logger})

    chunks = [content for content, _ in channel.calls]
    assert logger.error.called
    assert len(chunks) == 50
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "truncated" in chunks[-1].lower()
