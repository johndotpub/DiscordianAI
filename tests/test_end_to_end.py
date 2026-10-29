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


class FakeTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeUser:
    def __init__(self, user_id: int, *, bot: bool = False):
        self.id = user_id
        self.bot = bot
        self.name = f"user-{user_id}"
        self.mention = f"<@{user_id}>"


class FakeGuild:
    def __init__(self, guild_id: int, name: str = "Guild"):
        self.id = guild_id
        self.name = name
        self.text_channels = []
        self.forums = []
        self.channels = self.text_channels


class FakeChannel:
    def __init__(self, channel_id: int, name: str, guild: FakeGuild):
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.sent_messages: list[tuple[str, dict]] = []

    def typing(self):
        return FakeTyping()

    async def send(self, content: str, **kwargs):
        self.sent_messages.append((content, kwargs))


class FakeMessage:
    def __init__(self, *, author, channel, guild, mentions, content):
        self.id = 7001
        self.author = author
        self.channel = channel
        self.guild = guild
        self.mentions = mentions
        self.content = content
        self.replies: list[tuple[str, dict]] = []

    async def reply(self, content: str, **kwargs):
        self.replies.append((content, kwargs))


def _build_dependencies(bot, channel, openai_client):
    config = {
        "GPT_MODEL": "gpt-5-mini",
        "PERPLEXITY_MODEL": "sonar-pro",
        "SYSTEM_MESSAGE": SYSTEM_PROMPT,
        "OUTPUT_TOKENS": 1234,
        "PERPLEXITY_OUTPUT_TOKENS": 4321,
        "INPUT_TOKENS": 10000,
        "CONTEXT_WINDOW": 128000,
        "RATE_LIMIT": 5,
        "RATE_LIMIT_PER": 60,
        "MAX_URLS_PER_MESSAGE": 3,
        "MAX_TOTAL_SCRAPED_CHARS": 60000,
        "SCRAPE_DEADLINE_SECONDS": 20.0,
        "MAX_HISTORY_PER_USER": 50,
        "CONVERSATION_TTL_SECONDS": 1800,
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
            max_history_per_user=50,
            cleanup_interval=3600,
            conversation_ttl_seconds=1800,
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


@pytest.mark.asyncio
async def test_guild_mention_travels_the_real_pipeline():
    guild = FakeGuild(1)
    channel = FakeChannel(555, "general", guild)
    guild.text_channels.append(channel)
    guild.channels = guild.text_channels
    bot_user = FakeUser(1, bot=True)
    author = FakeUser(42)
    bot = SimpleNamespace(user=bot_user, guilds=[guild])
    message = FakeMessage(
        author=author,
        channel=channel,
        guild=guild,
        mentions=[bot_user],
        content=f"{bot_user.mention} {USER_TEXT}",
    )

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
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
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
    assert payload["max_completion_tokens"] == deps.config["OUTPUT_TOKENS"]

    conversation_key = conversation_key_for_message(message, is_dm=False)
    conversation = deps.conversation_manager.get_conversation(conversation_key=conversation_key)
    assert [entry["role"] for entry in conversation] == ["user", "assistant"]
    assert conversation[0]["content"] == USER_TEXT
    assert conversation[1]["content"] == RESPONSE

    assert len(RESPONSE) > MESSAGE_LIMIT
    assert len(message.replies) >= 2
    assert channel.sent_messages == []
    for content, kwargs in message.replies:
        assert len(content) <= MESSAGE_LIMIT
        assert kwargs["mention_author"] is False
        allowed_mentions = kwargs["allowed_mentions"]
        assert isinstance(allowed_mentions, discord.AllowedMentions)
        assert allowed_mentions.users == [message.author]
        assert allowed_mentions.replied_user is False

    assert message.replies[0][0].startswith(f"{message.author.mention} ")
    delivered_text = "".join(content for content, _kwargs in message.replies)
    assert delivered_text == f"{message.author.mention} {RESPONSE}"
