"""Long answers must be delivered completely instead of hitting a depth guard."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest

from src.discord_embeds import citation_embed_formatter
from src.message_splitter import (
    _split_embed_head,
    send_split_message,
    send_split_message_with_embed,
)

MENTION_PREFIX = "<@42> "
EMBED_SAFE_LIMIT = 3840


def _fence_lines_are_balanced(chunk: str) -> bool:
    return chunk.count("```") % 2 == 0


def _long_fence(line_count: int = 250) -> tuple[list[str], str]:
    lines = [f"print('code line {index:03d}')" for index in range(line_count)]
    return lines, "```python\n" + "\n".join(lines) + "\n```"


class RecordingChannel:
    """Capture plain channel sends without a real Discord connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send(self, content: str, **kwargs) -> None:
        self.calls.append((content, kwargs))


def _original_message() -> SimpleNamespace:
    author = SimpleNamespace(id=42, mention="<@42>", bot=False)
    original = SimpleNamespace(author=author)

    def to_reference(*, fail_if_not_exists: bool = True, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(fail_if_not_exists=fail_if_not_exists)

    original.to_reference = to_reference
    return original


def _reply_calls(channel: RecordingChannel) -> list[tuple[str, dict]]:
    return [call for call in channel.calls if "reference" in call[1]]


def _reply_texts(channel: RecordingChannel) -> list[str]:
    return [content for content, _kwargs in _reply_calls(channel)]


def _unlink_embed_citations(text: str) -> str:
    return re.sub(r"\[\[(\d+)\]\]\([^)]+\)", r"[\1]", text)


def _rendered_embed_texts(calls) -> list[str]:
    rendered: list[str] = []
    for content, kwargs in calls:
        rendered.append(content)
        embed = kwargs.get("embed")
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

    chunks = _reply_texts(channel)
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

    calls = _reply_calls(channel)
    assert calls[0][1]["embed"] is embed
    rendered = _rendered_embed_texts(calls)
    assert "".join(rendered) == f"{MENTION_PREFIX}{body}"
    assert not any("truncated" in text.lower() for text in rendered)


def _cited_body(sentence_count: int, filler_words: int) -> tuple[str, dict[str, str]]:
    filler = "word " * filler_words
    parts = [f"Sentence {index:02d} {filler}[{index + 1}]." for index in range(sentence_count)]
    body = " ".join(parts)
    citations = {
        str(index + 1): f"https://example.com/source/{index + 1}"
        for index in range(sentence_count)
    }
    return body, citations


def _all_delivered_texts(channel: RecordingChannel) -> list[str]:
    texts: list[str] = []
    for content, kwargs in _reply_calls(channel):
        texts.append(content)
        embed = kwargs.get("embed")
        if embed is not None and embed.description:
            texts.append(_unlink_embed_citations(embed.description))
    return texts


@pytest.mark.asyncio
async def test_cited_body_that_overflows_rendered_embed_is_delivered_once():
    body, citations = _cited_body(39, 13)
    _, metadata = citation_embed_formatter.create_citation_embed(body, citations)
    assert metadata["formatted_length"] > EMBED_SAFE_LIMIT
    channel = RecordingChannel()
    original = _original_message()
    embed = discord.Embed(description="placeholder")

    await send_split_message_with_embed(
        channel,
        body,
        {"logger": MagicMock()},
        embed,
        citations,
        original_message=original,
    )

    texts = _all_delivered_texts(channel)
    delivered = "".join(texts)
    assert delivered == body
    assert len(_reply_calls(channel)) == 2
    for index in range(39):
        assert delivered.count(f"Sentence {index:02d}") == 1
    assert "Sentence 38" in delivered


@pytest.mark.asyncio
async def test_uncited_body_that_fits_the_embed_is_delivered_as_one_embed():
    body, _ = _cited_body(39, 13)
    channel = RecordingChannel()
    original = _original_message()
    embed = discord.Embed(description="placeholder")

    await send_split_message_with_embed(
        channel,
        body,
        {"logger": MagicMock()},
        embed,
        {},
        original_message=original,
    )

    assert len(_reply_calls(channel)) == 1
    assert _reply_calls(channel)[0][0] == ""
    assert _reply_calls(channel)[0][1]["embed"] is embed
    assert embed.description == body


@pytest.mark.asyncio
async def test_delivery_count_does_not_grow_with_the_number_of_citations():
    body, _ = _cited_body(45, 13)
    counts = []

    for citation_count in (5, 39):
        citations = {
            str(index + 1): f"https://example.com/source/{index + 1}"
            for index in range(citation_count)
        }
        channel = RecordingChannel()
        original = _original_message()
        embed = discord.Embed(description="placeholder")

        await send_split_message_with_embed(
            channel,
            body,
            {"logger": MagicMock()},
            embed,
            citations,
            original_message=original,
        )
        counts.append(len(_reply_calls(channel)))

    assert counts == [2, 2]


@pytest.mark.asyncio
async def test_single_long_code_line_is_hard_wrapped_not_dropped():
    channel = RecordingChannel()
    fence = "```\n" + ("A" * 4992) + "\n```"
    assert len(fence) == 5000

    await send_split_message(channel, fence, {"logger": MagicMock()})

    chunks = [content for content, _ in channel.calls]
    assert len(chunks) > 1
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert sum(chunk.count("A") for chunk in chunks) == 4992
    assert all(_fence_lines_are_balanced(chunk) for chunk in chunks)
    assert not any("truncated" in chunk.lower() for chunk in chunks)


@pytest.mark.asyncio
async def test_long_fence_spanning_messages_delivers_every_line():
    channel = RecordingChannel()
    prose = ("Intro prose that arrives before the fence. " * 35).rstrip() + "\n"
    code_lines, fence = _long_fence()
    closing = "\nThe paragraph after the code still arrives."
    message = prose + fence + closing

    await send_split_message(channel, message, {"logger": MagicMock()})

    chunks = [content for content, _ in channel.calls]
    code_chunks = [chunk for chunk in chunks if chunk.startswith("```python")]
    delivered = "".join(chunks)

    assert len(chunks) >= 3
    assert len(code_chunks) >= 3
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert all(_fence_lines_are_balanced(chunk) for chunk in chunks)
    assert all(line in delivered for line in code_lines)
    assert closing.strip() in delivered
    assert not any("truncated" in chunk.lower() for chunk in chunks)


@pytest.mark.asyncio
async def test_long_fence_respects_the_first_chunk_mention_limit():
    channel = RecordingChannel()
    original = _original_message()
    code_lines, fence = _long_fence(300)

    await send_split_message(
        channel,
        fence,
        {"logger": MagicMock()},
        original_message=original,
        mention_prefix=MENTION_PREFIX,
    )

    chunks = _reply_texts(channel)
    delivered = "".join(chunks)

    assert chunks[0].startswith(MENTION_PREFIX)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert all(_fence_lines_are_balanced(chunk) for chunk in chunks)
    assert all(line in delivered for line in code_lines)


@pytest.mark.asyncio
async def test_chunk_cap_notice_reports_original_length_and_bot_limit():
    channel = RecordingChannel()
    body = "C" * 12000

    await send_split_message(channel, body, {"logger": MagicMock()}, _chunk_budget=2)

    chunks = [content for content, _ in channel.calls]
    assert len(chunks) == 2
    assert "12000" in chunks[-1]
    assert "bot's delivery limit" in chunks[-1].lower()
    assert "discord limits" not in chunks[-1].lower()


def test_embed_split_never_cuts_a_citation_marker():
    body = ("A" * 3839) + "[20]" + ("B" * 100)

    head, tail = _split_embed_head(body, {"20": "https://example.com/source/20"})

    assert head + tail == body
    assert not head.endswith("[")
    assert not tail.startswith("]")
    assert tail.startswith("[20]")


def test_embed_split_keeps_a_long_fence_balanced():
    _, fence = _long_fence(600)

    head, tail = _split_embed_head(fence, {})

    assert len(head) <= EMBED_SAFE_LIMIT
    assert _fence_lines_are_balanced(head)
    assert head.endswith("```")
    assert tail.startswith("```python")


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
