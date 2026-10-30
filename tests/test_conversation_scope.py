"""Conversation history must be keyed by DM/channel, never by user alone."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.caching import ResponseCache
from src.conversation_manager import ThreadSafeConversationManager
from src.message_processor import _process_message_core
from src.smart_orchestrator import _record_conversation_turn

LOGGER = logging.getLogger("test_conversation_scope")


def _record(manager, key, user_id, user_text, assistant_text="ack"):
    """Record a turn using the same helper the orchestrator uses."""
    request = SimpleNamespace(
        message=user_text,
        user=SimpleNamespace(id=user_id),
        conversation_manager=manager,
        logger=LOGGER,
        conversation_key=key,
    )
    _record_conversation_turn(request, assistant_text, "openai", "gpt-test")


def _message(*, user_id, channel_id, guild_id=None, content="hello"):
    return SimpleNamespace(
        id=1,
        author=SimpleNamespace(id=user_id, name="user", mention=f"<@{user_id}>"),
        channel=SimpleNamespace(id=channel_id, send=AsyncMock()),
        guild=(SimpleNamespace(id=guild_id, name="guild") if guild_id is not None else None),
        content=content,
    )


def _deps(manager):
    return {
        "logger": LOGGER,
        "rate_limiter": MagicMock(),
        "conversation_manager": manager,
        "client": None,
        "perplexity_client": None,
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "GPT_MODEL": "gpt-test",
        "SYSTEM_MESSAGE": "system",
        "OUTPUT_TOKENS": 100,
        "config": {},
    }


async def _guild_prompt(manager, *, user_id, guild_id, channel_id, content="<@1> hello"):
    """Run a guild message through the processor and capture its prompt."""
    captured = {}

    async def fake_get_smart_response(request, conversation_summary, clients, config, orch):
        captured["request"] = request
        captured["summary"] = conversation_summary
        return ("public reply", False, None)

    message = _message(
        user_id=user_id,
        channel_id=channel_id,
        guild_id=guild_id,
        content=content,
    )

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", fake_get_smart_response),
        patch("src.message_processor.send_formatted_message", AsyncMock()),
    ):
        await _process_message_core(message, _deps(manager), is_dm=False)

    return captured["summary"], captured["request"]


@pytest.mark.asyncio
async def test_dm_turn_is_not_replayed_into_guild_prompt():
    manager = ThreadSafeConversationManager()
    dm_only_marker = "ZXQ-DM-ONLY-MARKER-9f4c"

    _record(manager, "dm:42", 42, f"remember {dm_only_marker}", "noted")

    summary, request = await _guild_prompt(
        manager,
        user_id=42,
        guild_id=100,
        channel_id=200,
        content="<@1> what did I tell you?",
    )

    assert dm_only_marker not in str(summary)
    assert request.conversation_key == "g:100:c:200"


@pytest.mark.asyncio
async def test_channels_for_same_user_are_disjoint():
    manager = ThreadSafeConversationManager()

    _record(manager, "g:100:c:201", 42, "alpha-only-marker", "alpha answer")

    summary, request = await _guild_prompt(
        manager,
        user_id=42,
        guild_id=100,
        channel_id=202,
    )

    assert "alpha-only-marker" not in str(summary)
    assert request.conversation_key == "g:100:c:202"


@pytest.mark.asyncio
async def test_two_users_in_same_channel_share_one_transcript():
    manager = ThreadSafeConversationManager()
    key = "g:100:c:203"

    _record(manager, key, 1, "first-user-line", "first answer")
    _record(manager, key, 2, "second-user-line", "second answer")

    summary, request = await _guild_prompt(
        manager,
        user_id=1,
        guild_id=100,
        channel_id=203,
    )

    transcript = str(summary)
    assert "first-user-line" in transcript
    assert "second-user-line" in transcript
    assert request.conversation_key == key


@pytest.mark.asyncio
async def test_thread_and_parent_channel_are_separate_conversations():
    manager = ThreadSafeConversationManager()
    parent_key = "g:999:c:300"
    thread_key = "g:999:c:301"

    _record(manager, parent_key, 5, "parent-only-marker", "parent answer")

    summary, request = await _guild_prompt(
        manager,
        user_id=5,
        guild_id=999,
        channel_id=301,
    )

    assert "parent-only-marker" not in str(summary)
    assert request.conversation_key == thread_key


def test_recent_ai_service_does_not_cross_conversations():
    manager = ThreadSafeConversationManager()

    manager.add_message(
        conversation_key="dm:77",
        role="assistant",
        content="perplexity answer",
        metadata={"ai_service": "perplexity"},
    )

    assert manager.get_recent_ai_service(conversation_key="dm:77") == "perplexity"
    assert manager.get_recent_ai_service(conversation_key="g:1:c:2") is None


def test_cached_dm_answer_is_not_served_for_guild_key():
    cache = ResponseCache(max_size=10, default_ttl=300.0)
    answer = "cached answer from the direct-message conversation"
    base_context = {
        "model": "gpt-test",
        "system_message": "system",
        "user_id": "88",
        "conversation_digest": "same-digest",
        "has_conversation": False,
    }
    dm_context = {**base_context, "conversation_key": "dm:88"}
    guild_context = {**base_context, "conversation_key": "g:1:c:2"}

    salt = "local:heuristic@1:1"
    cache.cache_response("same question", dm_context, answer, salt=salt)

    assert cache.get_cached_response("same question", dm_context, salt=salt) == answer
    assert cache.get_cached_response("same question", guild_context, salt=salt) is None


def test_history_cap_applies_per_conversation():
    manager = ThreadSafeConversationManager(max_history_per_user=3)

    for i in range(5):
        manager.add_message(
            conversation_key="g:1:c:1",
            role="user",
            content=f"channel-a-{i}",
        )
    for i in range(2):
        manager.add_message(
            conversation_key="g:1:c:2",
            role="user",
            content=f"channel-b-{i}",
        )

    channel_a = manager.get_conversation(conversation_key="g:1:c:1")
    channel_b = manager.get_conversation(conversation_key="g:1:c:2")

    assert [message["content"] for message in channel_a] == [
        "channel-a-2",
        "channel-a-3",
        "channel-a-4",
    ]
    assert [message["content"] for message in channel_b] == [
        "channel-b-0",
        "channel-b-1",
    ]
