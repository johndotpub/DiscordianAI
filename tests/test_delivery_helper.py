"""Tests for the single outbound delivery helper."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.config import EMBED_SAFE_LIMIT
from src.message_splitter import (
    send_formatted_message,
    send_split_message,
    send_split_message_with_embed,
)

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _deps() -> dict[str, MagicMock]:
    return {"logger": MagicMock()}


def _channel() -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    return channel


def _original_message() -> MagicMock:
    author = MagicMock()
    author.mention = "<@123>"
    original_message = MagicMock(spec=discord.Message)
    original_message.author = author
    original_message.reply = AsyncMock()
    return original_message


def _assert_reply_policy(original_message: MagicMock) -> None:
    for call in original_message.reply.call_args_list:
        kwargs = call.kwargs
        assert kwargs["mention_author"] is False
        allowed_mentions = kwargs["allowed_mentions"]
        assert isinstance(allowed_mentions, discord.AllowedMentions)
        assert allowed_mentions.users == [original_message.author]
        assert allowed_mentions.replied_user is False


def test_only_one_allowed_mentions_construction() -> None:
    """All outbound mention policy must come from the single delivery helper."""
    source = "\n".join(path.read_text(encoding="utf-8") for path in SRC_DIR.rglob("*.py"))
    assert source.count("discord.AllowedMentions") == 1


@pytest.mark.asyncio
async def test_send_split_message_applies_reply_policy() -> None:
    channel = _channel()
    original_message = _original_message()

    await send_split_message(
        channel,
        "A" * 4500,
        _deps(),
        original_message=original_message,
        suppress_embeds=True,
    )

    assert original_message.reply.call_count >= 2
    _assert_reply_policy(original_message)
    for call in original_message.reply.call_args_list:
        assert call.kwargs["suppress_embeds"] is True


@pytest.mark.asyncio
async def test_send_split_message_with_embed_applies_reply_policy() -> None:
    channel = _channel()
    original_message = _original_message()
    embed = discord.Embed(description="head")
    citations = {"1": "https://example.com/one", "2": "https://example.com/two"}
    content = "A" * (EMBED_SAFE_LIMIT + 50) + " [1] " + ("B" * 50) + " [2]"

    await send_split_message_with_embed(
        channel,
        content,
        _deps(),
        embed,
        citations,
        original_message=original_message,
        mention_prefix=f"{original_message.author.mention} ",
    )

    assert original_message.reply.call_count >= 2
    _assert_reply_policy(original_message)
    first_call = original_message.reply.call_args_list[0]
    assert first_call.args[0].startswith(f"{original_message.author.mention} ")
    assert first_call.kwargs["embed"] is embed
    continuation = original_message.reply.call_args_list[-1].kwargs["embed"]
    assert continuation.footer.text == "🌐 Web search results (continued)"


@pytest.mark.asyncio
async def test_send_formatted_message_applies_reply_policy() -> None:
    channel = _channel()
    original_message = _original_message()
    embed = discord.Embed(description="formatted")
    embed_data = {
        "embed": embed,
        "clean_text": "Formatted [1]",
        "embed_metadata": {"was_truncated": False},
    }

    await send_formatted_message(
        channel,
        "Formatted [1]",
        _deps(),
        embed_data=embed_data,
        original_message=original_message,
        mention_prefix=f"{original_message.author.mention} ",
    )

    original_message.reply.assert_called_once()
    _assert_reply_policy(original_message)
    assert original_message.reply.call_args.kwargs["embed"] is embed


@pytest.mark.asyncio
async def test_send_without_original_message_uses_channel_send() -> None:
    channel = _channel()

    await send_split_message(channel, "A" * 4500, _deps(), suppress_embeds=True)

    assert channel.send.call_count >= 2
    for call in channel.send.call_args_list:
        assert call.kwargs == {"suppress_embeds": True}


@pytest.mark.asyncio
async def test_embed_paths_attach_embed_without_original_message() -> None:
    channel = _channel()
    embed = discord.Embed(description="head")
    citations = {"1": "https://example.com/one", "2": "https://example.com/two"}
    content = "A" * (EMBED_SAFE_LIMIT + 50) + " [1] " + ("B" * 50) + " [2]"

    await send_split_message_with_embed(channel, content, _deps(), embed, citations)

    assert channel.send.call_count >= 2
    assert channel.send.call_args_list[0].kwargs["embed"] is embed
    for call in channel.send.call_args_list:
        assert call.kwargs["embed"] is not None
    continuation = channel.send.call_args_list[-1].kwargs["embed"]
    assert continuation.footer.text == "🌐 Web search results (continued)"


@pytest.mark.asyncio
async def test_embed_fallback_text_parts_honour_suppress_embeds() -> None:
    channel = _channel()
    response = MagicMock()
    response.status = 400
    response.text = "Bad Request"
    error = discord.HTTPException(response=response, message="Embed failed")
    channel.send = AsyncMock(side_effect=[error, None])
    embed = discord.Embed(description="embed")
    embed_data = {"embed": embed, "clean_text": "Fallback text", "embed_metadata": {}}

    await send_formatted_message(
        channel,
        "Fallback text",
        _deps(),
        suppress_embeds=True,
        embed_data=embed_data,
    )

    assert channel.send.call_count == 2
    assert channel.send.call_args_list[0].kwargs["embed"] is embed
    fallback = channel.send.call_args_list[1]
    assert fallback.args[0] == "Fallback text"
    assert fallback.kwargs["suppress_embeds"] is True
