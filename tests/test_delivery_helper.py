"""Tests for the single outbound delivery helper."""

import ast
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
    original_message.id = 456
    original_message.channel = MagicMock(id=99)
    original_message.author = author

    def to_reference(*, fail_if_not_exists: bool = True, **_kwargs) -> discord.MessageReference:
        return discord.MessageReference(
            message_id=original_message.id,
            channel_id=original_message.channel.id,
            fail_if_not_exists=fail_if_not_exists,
        )

    original_message.to_reference = MagicMock(side_effect=to_reference)
    return original_message


def _http_exception(status: int, code: int = 0) -> discord.HTTPException:
    response = MagicMock()
    response.status = status
    response.reason = "Bad Request"
    return discord.HTTPException(
        response=response,
        message={"code": code, "message": "Unknown Message"},
    )


def _reply_calls(channel: MagicMock) -> list:
    return [call for call in channel.send.call_args_list if "reference" in call.kwargs]


def _assert_reply_policy(channel: MagicMock, original_message: MagicMock) -> None:
    calls = _reply_calls(channel)
    assert calls
    for call in calls:
        kwargs = call.kwargs
        assert kwargs["mention_author"] is False
        reference = kwargs["reference"]
        assert isinstance(reference, discord.MessageReference)
        assert reference.fail_if_not_exists is False
        allowed_mentions = kwargs["allowed_mentions"]
        assert isinstance(allowed_mentions, discord.AllowedMentions)
        assert allowed_mentions.users == [original_message.author]
        assert allowed_mentions.replied_user is False


def _assert_deny_all_mentions(kwargs: dict) -> None:
    allowed_mentions = kwargs["allowed_mentions"]
    assert isinstance(allowed_mentions, discord.AllowedMentions)
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles == []
    assert allowed_mentions.users == []
    assert allowed_mentions.replied_user is False
    parse = allowed_mentions.to_dict()["parse"]
    assert "everyone" not in parse
    assert "roles" not in parse


def _allowed_mentions_call(
    func: ast.expr, discord_names: set[str], allowed_names: set[str]
) -> bool:
    """Return True when a call expression constructs AllowedMentions."""
    if isinstance(func, ast.Name) and func.id in allowed_names:
        return True
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "AllowedMentions"
        and isinstance(func.value, ast.Name)
        and func.value.id in discord_names
    )


def _enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """Return the nearest function, lambda, or module scope label."""
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        if isinstance(current, ast.Lambda):
            return "<lambda>"
        current = parents.get(current)
    return "<module>"


def _allowed_mentions_constructions(directory: Path = SRC_DIR) -> list[tuple[str, str]]:
    """Return every module and function that constructs AllowedMentions.

    Every ``ast.Call`` is inspected, including calls inside comprehensions,
    lambdas, default arguments, and decorators, so a new construction cannot
    hide in an expression context the old visitor did not enter.
    """
    constructions: list[tuple[str, str]] = []

    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        discord_names = {"discord"}
        allowed_names = {"AllowedMentions"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "discord":
                        discord_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "discord":
                for alias in node.names:
                    if alias.name == "AllowedMentions":
                        allowed_names.add(alias.asname or alias.name)

        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        constructions.extend(
            (str(path.relative_to(directory)), _enclosing_scope(node, parents))
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _allowed_mentions_call(node.func, discord_names, allowed_names)
        )

    return constructions


def test_only_one_allowed_mentions_construction() -> None:
    """All outbound mention policy must come from the single delivery helper."""
    assert _allowed_mentions_constructions() == [("message_splitter.py", "_deliver")]


@pytest.mark.asyncio
async def test_deleted_question_reference_does_not_fail() -> None:
    """A reply reference lets Discord fall back to a normal send when it is gone."""
    channel = _channel()
    original_message = _original_message()

    await send_formatted_message(
        channel,
        "The answer",
        _deps(),
        original_message=original_message,
        mention_prefix=f"{original_message.author.mention} ",
    )

    channel.send.assert_awaited_once()
    reference = channel.send.call_args.kwargs["reference"]
    assert reference.fail_if_not_exists is False
    assert channel.send.call_args.args[0] == f"{original_message.author.mention} The answer"
    _assert_reply_policy(channel, original_message)


@pytest.mark.asyncio
async def test_reply_failure_for_another_reason_is_not_replaced() -> None:
    channel = _channel()
    channel.send = AsyncMock(side_effect=_http_exception(403, 50013))
    original_message = _original_message()

    with pytest.raises(discord.HTTPException):
        await send_formatted_message(
            channel,
            "The answer",
            _deps(),
            original_message=original_message,
        )

    channel.send.assert_awaited_once()


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

    assert len(_reply_calls(channel)) >= 2
    _assert_reply_policy(channel, original_message)
    for call in _reply_calls(channel):
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

    assert len(_reply_calls(channel)) >= 2
    _assert_reply_policy(channel, original_message)
    first_call = _reply_calls(channel)[0]
    assert first_call.args[0].startswith(f"{original_message.author.mention} ")
    assert first_call.kwargs["embed"] is embed
    continuation = _reply_calls(channel)[-1].kwargs["embed"]
    assert continuation.footer.text == "🌐 Web search results (continued)"


@pytest.mark.asyncio
async def test_truncated_embed_delivery_appends_one_notice() -> None:
    channel = _channel()
    embed = discord.Embed(description="Partial answer [1]")
    embed_data = {
        "embed": embed,
        "clean_text": "Partial answer [1]",
        "embed_metadata": {},
    }
    citations = {"1": "https://example.com/one"}

    await send_formatted_message(
        channel,
        "Partial answer [1]",
        _deps(),
        embed_data=embed_data,
        citations=citations,
        truncated=True,
    )

    channel.send.assert_called_once()
    sent_embed = channel.send.call_args.kwargs["embed"]
    assert sent_embed.description.count("cut off at the length limit") == 1


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

    channel.send.assert_called_once()
    _assert_reply_policy(channel, original_message)
    assert channel.send.call_args.kwargs["embed"] is embed


@pytest.mark.asyncio
async def test_send_without_original_message_uses_channel_send() -> None:
    channel = _channel()

    await send_split_message(channel, "A" * 4500, _deps(), suppress_embeds=True)

    assert channel.send.call_count >= 2
    for call in channel.send.call_args_list:
        assert call.kwargs["suppress_embeds"] is True
        _assert_deny_all_mentions(call.kwargs)


@pytest.mark.asyncio
async def test_channel_send_without_original_message_denies_all_mentions() -> None:
    channel = _channel()

    await send_split_message(channel, "A short answer", _deps())

    channel.send.assert_called_once()
    _assert_deny_all_mentions(channel.send.call_args.kwargs)


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


def test_allowed_mentions_guard_sees_a_call_in_a_comprehension(tmp_path):
    """A construction inside a comprehension is not invisible to the guard."""
    module = tmp_path / "sample.py"
    module.write_text(
        "import discord\nVALUES = [discord.AllowedMentions() for _ in range(1)]\n",
        encoding="utf-8",
    )

    assert _allowed_mentions_constructions(tmp_path) == [("sample.py", "<module>")]
