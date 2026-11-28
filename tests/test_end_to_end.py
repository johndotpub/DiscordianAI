"""End-to-end guild mention through the real processing pipeline.

Only the Discord objects and the OpenAI client's ``create`` call are faked.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from src import message_router
from src.config import MESSAGE_LIMIT
from src.conversation_manager import (
    ThreadSafeConversationManager,
    conversation_key_for_message,
)
from src.dependencies import BotDependencies
from src.rate_limits import RateLimiter

SYSTEM_PROMPT = "You are the end-to-end test assistant. Answer plainly."
USER_TEXT = "Please explain the deterministic end-to-end path."
RESPONSE = " ".join(
    f"Paragraph {index}: this is a deterministic sentence used for splitting."
    for index in range(80)
)


def _build_dependencies(bot, channel, openai_client):
    config = {
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "SYSTEM_MESSAGE": SYSTEM_PROMPT,
        "OUTPUT_TOKENS": 1234,
        "PERPLEXITY_OUTPUT_TOKENS": 4321,
        "INPUT_TOKENS": 10000,
        "CONTEXT_WINDOW": 1000000,
        "RATE_LIMIT": 5,
        "RATE_LIMIT_PER": 60,
        "MAX_HISTORY_PER_USER": 100,
        "CONVERSATION_TTL_SECONDS": 7200,
        "USER_LOCK_CLEANUP_INTERVAL": 3600,
        "LOOKBACK_MESSAGES_FOR_CONSISTENCY": 6,
        "ENTITY_DETECTION_MIN_WORDS": 10,
        "ALLOWED_CHANNELS": [],
        "ALLOWED_CHANNEL_IDS": [channel.id],
        "ALLOWED_GUILDS": [],
        "ALLOWED_GUILD_IDS": [],
    }
    logger = logging.getLogger("end-to-end-test")
    logger.addHandler(logging.NullHandler())
    return BotDependencies(
        bot=bot,
        logger=logger,
        config=config,
        client=openai_client,
        perplexity_client=None,
        rate_limiter=RateLimiter(),
        conversation_manager=ThreadSafeConversationManager(
            max_history_per_user=100,
            cleanup_interval=3600,
            conversation_ttl_seconds=7200,
        ),
        allowed_channels=[],
        allowed_channel_ids=[channel.id],
        allowed_guilds=[],
        allowed_guild_ids=[],
        rate_limit=config["RATE_LIMIT"],
        rate_limit_period=config["RATE_LIMIT_PER"],
        gpt_model=config["GPT_MODEL"],
        perplexity_model=config["PERPLEXITY_MODEL"],
        system_message=config["SYSTEM_MESSAGE"],
        output_tokens=config["OUTPUT_TOKENS"],
        perplexity_output_tokens=config["PERPLEXITY_OUTPUT_TOKENS"],
        input_tokens=config["INPUT_TOKENS"],
        context_window=config["CONTEXT_WINDOW"],
    )


@pytest.mark.parametrize(
    ("base_url", "cap_param"),
    [
        ("https://ollama.com/v1/", "max_tokens"),
        ("https://api.openai.com/v1/", "max_completion_tokens"),
    ],
)
@pytest.mark.asyncio
async def test_guild_mention_travels_the_real_pipeline(base_url: str, cap_param: str, e2e_scene):
    scene = e2e_scene(USER_TEXT)
    channel = scene.channel
    message = scene.message
    bot = scene.bot

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=RESPONSE),
                finish_reason="stop",
            )
        ]
    )
    create = AsyncMock(return_value=response)
    openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        base_url=base_url,
    )
    deps = _build_dependencies(bot, channel, openai_client)

    await message_router.handle_incoming_message(message, deps, bot)

    create.assert_awaited_once()
    payload = create.await_args.kwargs
    assert payload["model"] == deps.config["GPT_MODEL"]
    assert payload["model"] != deps.config["PERPLEXITY_MODEL"]
    assert payload["messages"][0] == {
        "role": "system",
        "content": deps.config["SYSTEM_MESSAGE"],
    }
    assert payload["messages"][-1] == {"role": "user", "content": USER_TEXT}
    other_cap_param = (
        "max_tokens" if cap_param == "max_completion_tokens" else "max_completion_tokens"
    )
    assert payload[cap_param] == deps.config["OUTPUT_TOKENS"]
    assert other_cap_param not in payload
    assert payload["reasoning_effort"] == "high"

    conversation_key = conversation_key_for_message(message, is_dm=False)
    conversation = deps.conversation_manager.get_conversation(conversation_key=conversation_key)
    assert [entry["role"] for entry in conversation] == ["user", "assistant"]
    assert conversation[0]["content"] == USER_TEXT
    assert conversation[1]["content"] == RESPONSE

    assert len(RESPONSE) > MESSAGE_LIMIT
    assert len(channel.sent_messages) >= 2
    for content, kwargs in channel.sent_messages:
        assert len(content) <= MESSAGE_LIMIT
        assert kwargs["mention_author"] is False
        allowed_mentions = kwargs["allowed_mentions"]
        assert isinstance(allowed_mentions, discord.AllowedMentions)
        assert allowed_mentions.users == [message.author]
        assert allowed_mentions.replied_user is False

    assert channel.sent_messages[0][0].startswith(f"{message.author.mention} ")
    delivered_text = "".join(content for content, _kwargs in channel.sent_messages)
    assert delivered_text == f"{message.author.mention} {RESPONSE}"


@pytest.mark.asyncio
async def test_length_finish_reason_delivers_partial_answer_with_one_notice(e2e_scene):
    scene = e2e_scene(USER_TEXT)
    channel = scene.channel
    message = scene.message
    bot = scene.bot
    author = scene.author
    partial = "A partial answer that stops mid-sentence"

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=partial),
                finish_reason="length",
            )
        ]
    )
    create = AsyncMock(return_value=response)
    openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        base_url="https://ollama.com/v1/",
    )
    deps = _build_dependencies(bot, channel, openai_client)

    await message_router.handle_incoming_message(message, deps, bot)

    assert len(channel.sent_messages) == 1
    content = channel.sent_messages[0][0]
    assert content.startswith(f"{author.mention} {partial}")
    assert content.count("cut off at the length limit") == 1
    assert not content.endswith(partial)

    conversation_key = conversation_key_for_message(message, is_dm=False)
    conversation = deps.conversation_manager.get_conversation(conversation_key=conversation_key)
    assert conversation[1]["content"] == partial
    assert "cut off at the length limit" not in conversation[1]["content"]


@pytest.mark.asyncio
async def test_model_output_mentions_are_neutralised_in_delivery(e2e_scene):
    scene = e2e_scene(USER_TEXT)
    channel = scene.channel
    message = scene.message
    bot = scene.bot
    author = scene.author
    hostile = "Hello @everyone @here <@123> <@&456> <#789>"

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=hostile),
                finish_reason="stop",
            )
        ]
    )
    create = AsyncMock(return_value=response)
    openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        base_url="https://ollama.com/v1/",
    )
    deps = _build_dependencies(bot, channel, openai_client)

    await message_router.handle_incoming_message(message, deps, bot)

    assert len(channel.sent_messages) == 1
    content, kwargs = channel.sent_messages[0]
    for raw in ("@everyone", "@here", "<@123>", "<@&456>", "<#789>"):
        assert raw not in content
    assert "@\u200beveryone" in content
    assert "@\u200bhere" in content
    assert "<@\u200b123>" in content
    assert "<@&\u200b456>" in content
    assert "<#\u200b789>" in content
    allowed_mentions = kwargs["allowed_mentions"]
    assert isinstance(allowed_mentions, discord.AllowedMentions)
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles == []
    assert allowed_mentions.users == [author]
