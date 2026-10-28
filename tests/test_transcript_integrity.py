"""Transcript integrity regressions: turn pairing and empty-message guards."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import ERROR_MESSAGES
from src.conversation_manager import ThreadSafeConversationManager
from src.message_processor import _process_message_core
from src.smart_orchestrator import _record_conversation_turn

LOGGER = logging.getLogger("test_transcript_integrity")

ORPHAN_TRANSCRIPT = [
    {"role": "assistant", "content": "A2"},
    {"role": "user", "content": "Q1"},
    {"role": "assistant", "content": "A1"},
    {"role": "user", "content": "Q2"},
    {"role": "assistant", "content": "A3"},
]


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


def _message(*, content, user_id=1, guild_id=10, channel_id=20, is_dm=False):
    return SimpleNamespace(
        id=1,
        author=SimpleNamespace(id=user_id, name="user", mention=f"<@{user_id}>"),
        channel=SimpleNamespace(id=channel_id, send=AsyncMock()),
        guild=(None if is_dm else SimpleNamespace(id=guild_id, name="guild")),
        content=content,
    )


def _orphan_manager():
    manager = ThreadSafeConversationManager()
    manager.update_conversation(
        conversation_key="dm:99",
        conversation=list(ORPHAN_TRANSCRIPT),
    )
    return manager


async def _process_and_capture_sends(manager, message, *, is_dm):
    sent = []

    async def capture_send(_channel, content, *_args, **_kwargs):
        sent.append(content)
        return True

    api_call = AsyncMock(return_value=("unexpected model reply", False, None))

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", api_call),
        patch("src.message_processor.send_formatted_message", side_effect=capture_send),
        patch("src.message_processor.safe_discord_send", side_effect=capture_send),
    ):
        await _process_message_core(message, _deps(manager), is_dm=is_dm)

    return api_call, sent


@pytest.mark.asyncio
async def test_bare_mention_does_not_call_model_write_history_or_stay_silent():
    manager = ThreadSafeConversationManager()
    message = _message(content="<@123>", is_dm=False)

    api_call, sent = await _process_and_capture_sends(manager, message, is_dm=False)

    api_call.assert_not_called()
    assert manager.get_conversation(conversation_key="g:10:c:20") == []
    assert sent == [ERROR_MESSAGES["no_response_generated"]]


@pytest.mark.asyncio
async def test_whitespace_only_dm_is_treated_as_empty():
    manager = ThreadSafeConversationManager()
    message = _message(content="   \n\t", is_dm=True)

    api_call, sent = await _process_and_capture_sends(manager, message, is_dm=True)

    api_call.assert_not_called()
    assert manager.get_conversation(conversation_key="dm:1") == []
    assert sent == [ERROR_MESSAGES["no_response_generated"]]


def test_rebuilt_transcript_never_starts_with_assistant_and_drops_orphan():
    summary = _orphan_manager().get_conversation_summary_formatted(
        conversation_key="dm:99",
    )

    roles = [message["role"] for message in summary]
    assert roles
    assert roles[0] == "user"
    for index, role in enumerate(roles):
        if role == "assistant":
            assert index > 0
            assert roles[index - 1] == "user"

    assert [message["content"] for message in summary] == ["Q1", "A1", "Q2", "A3"]


def test_question_after_orphan_pairs_with_its_own_answer():
    summary = _orphan_manager().get_conversation_summary_formatted(
        conversation_key="dm:99",
    )

    paired_answers = {}
    for index, message in enumerate(summary[:-1]):
        if message["role"] == "user" and summary[index + 1]["role"] == "assistant":
            paired_answers[message["content"]] = summary[index + 1]["content"]

    assert paired_answers["Q1"] == "A1"
    assert paired_answers["Q1"] != "A2"


def test_newest_answer_is_present_in_summary():
    summary = _orphan_manager().get_conversation_summary_formatted(
        conversation_key="dm:99",
    )

    assert any(
        message["role"] == "assistant" and message["content"] == "A3" for message in summary
    )


@pytest.mark.parametrize("empty_response", ["", "   \n\t"])
def test_empty_assistant_response_is_not_recorded_as_a_turn(empty_response):
    manager = ThreadSafeConversationManager()
    request = SimpleNamespace(
        message="Q1",
        user=SimpleNamespace(id=1),
        conversation_manager=manager,
        logger=LOGGER,
        conversation_key="dm:1",
    )

    _record_conversation_turn(request, empty_response, "openai", "gpt-test")

    assert manager.get_conversation(conversation_key="dm:1") == []


def test_empty_assistant_message_with_metadata_is_not_stored():
    manager = ThreadSafeConversationManager()

    manager.add_message(
        conversation_key="dm:1",
        role="assistant",
        content="",
        metadata={"ai_service": "openai", "model": "gpt-test"},
    )

    assert manager.get_conversation(conversation_key="dm:1") == []
