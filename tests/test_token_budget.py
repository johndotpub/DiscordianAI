"""Token-budget enforcement tests for prompt construction."""

from unittest.mock import MagicMock

import pytest

from src.caching import response_cache
from src.message_builder import (
    TRUNCATION_MARKER,
    build_messages,
    estimate_messages_tokens,
)
from src.models import AIRequest, OpenAIConfig
from src.openai_processing import process_openai_message
from tests.helpers import FakeResponse

CURRENT = "What did we decide in the latest turn?"


class RecordingClient:
    """Fake provider client that records the payload it receives."""

    def __init__(self, response_text: str = "Recorded response."):
        self.response_text = response_text
        self.calls: list[dict] = []
        self.chat = self.Chat(self)
        self.responses = self.Responses(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **kwargs):
                self.client.calls.append(kwargs)
                return FakeResponse(self.client.response_text)

    class Responses:
        def __init__(self, client):
            self.client = client

        async def create(self, *_args, **kwargs):
            self.client.calls.append(kwargs)
            return FakeResponse(self.client.response_text)


def _make_request(message: str = CURRENT, logger=None) -> AIRequest:
    user = MagicMock()
    user.id = 12345
    return AIRequest(
        message=message,
        user=user,
        conversation_manager=MagicMock(),
        logger=logger or MagicMock(),
    )


def _history(turns: int, *, body_chars: int = 90) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for index in range(turns):
        history.append(
            {
                "role": "user",
                "content": f"Q{index:03d} " + ("question " * body_chars)[:body_chars],
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": f"A{index:03d} " + ("answer " * body_chars)[:body_chars],
            }
        )
    return history


@pytest.mark.asyncio
async def test_two_hundred_turn_history_is_trimmed_and_request_is_made():
    response_cache.cache.clear()
    client = RecordingClient()
    history = _history(200)
    config = OpenAIConfig(
        output_tokens=100,
        input_tokens=2000,
        context_window=200000,
    )

    result = await process_openai_message(_make_request(), history, client, config)

    assert result == "Recorded response."
    assert client.calls
    messages = client.calls[0]["messages"]
    assert estimate_messages_tokens(messages) <= 2000
    assert len(messages) < len(history) + 2


@pytest.mark.asyncio
async def test_oldest_turns_are_dropped_but_newest_turn_and_current_survive():
    response_cache.cache.clear()
    client = RecordingClient()
    history = _history(80)
    config = OpenAIConfig(
        output_tokens=50,
        input_tokens=500,
        context_window=200000,
    )

    await process_openai_message(_make_request(), history, client, config)

    messages = client.calls[0]["messages"]
    contents = [message["content"] for message in messages]
    joined = "\n".join(contents)
    assert "Q000" not in joined
    assert "Q079" in joined
    assert "A079" in joined
    assert messages[-1] == {"role": "user", "content": CURRENT}


def test_single_oversized_message_is_truncated_with_visible_marker():
    logger = MagicMock()
    oversized = "Z" * 10000

    messages = build_messages(
        "You are concise.",
        oversized,
        None,
        input_tokens=150,
        output_tokens=50,
        context_window=200000,
        logger=logger,
    )

    current = messages[-1]["content"]
    assert len(current) < len(oversized)
    assert TRUNCATION_MARKER in current
    assert estimate_messages_tokens(messages) <= 150
    assert logger.info.call_count == 1


def test_no_trimming_and_no_log_when_prompt_is_comfortably_inside_budget():
    logger = MagicMock()
    history = [
        {"role": "user", "content": "Name a novel by Frank Herbert."},
        {"role": "assistant", "content": "Dune."},
    ]

    messages = build_messages(
        "You are helpful.",
        CURRENT,
        history,
        input_tokens=250000,
        output_tokens=16384,
        context_window=1000000,
        logger=logger,
    )

    assert messages == [
        {"role": "system", "content": "You are helpful."},
        *history,
        {"role": "user", "content": CURRENT},
    ]
    logger.info.assert_not_called()
    logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_low_input_tokens_changes_the_request_outcome():
    response_cache.cache.clear()
    history = _history(50)
    high_client = RecordingClient()
    low_client = RecordingClient()

    await process_openai_message(
        _make_request(),
        history,
        high_client,
        OpenAIConfig(output_tokens=100, input_tokens=100000, context_window=200000),
    )
    response_cache.cache.clear()
    await process_openai_message(
        _make_request(),
        history,
        low_client,
        OpenAIConfig(output_tokens=100, input_tokens=300, context_window=200000),
    )

    high_messages = high_client.calls[0]["messages"]
    low_messages = low_client.calls[0]["messages"]
    assert len(low_messages) < len(high_messages)
    assert estimate_messages_tokens(low_messages) <= 300


@pytest.mark.asyncio
async def test_context_window_conflict_warns_and_still_sends_fitting_request():
    response_cache.cache.clear()
    logger = MagicMock()
    client = RecordingClient()
    history = _history(100)
    config = OpenAIConfig(
        output_tokens=5000,
        input_tokens=10000,
        context_window=9000,
    )

    result = await process_openai_message(
        _make_request(logger=logger),
        history,
        client,
        config,
    )

    assert result == "Recorded response."
    assert client.calls
    warning_text = " ".join(
        str(argument) for call in logger.warning.call_args_list for argument in call.args
    )
    assert "INPUT_TOKENS" in warning_text
    assert "OUTPUT_TOKENS" in warning_text
    messages = client.calls[0]["messages"]
    assert estimate_messages_tokens(messages) + config.output_tokens <= config.context_window


def test_explicit_shared_limits_cap_the_perplexity_budget():
    """A lowered INPUT_TOKENS or CONTEXT_WINDOW still limits Sonar prompts."""
    from src.message_processor import _perplexity_service_config

    deps = {
        "SYSTEM_MESSAGE": "System prompt",
        "OUTPUT_TOKENS": 16384,
    }
    config = {
        "INPUT_TOKENS": 500,
        "CONTEXT_WINDOW": 4000,
        "PERPLEXITY_INPUT_TOKENS": 111000,
        "PERPLEXITY_CONTEXT_WINDOW": 128000,
        "PERPLEXITY_OUTPUT_TOKENS": 100,
    }

    resolved = _perplexity_service_config(deps, config, "perplexity/sonar")

    assert resolved.input_tokens == 500
    assert resolved.context_window == 4000


def test_default_shared_limits_do_not_replace_the_perplexity_budget():
    """The Sonar defaults stay in force when the operator changed nothing."""
    from src.message_processor import _perplexity_service_config

    deps = {
        "SYSTEM_MESSAGE": "System prompt",
        "OUTPUT_TOKENS": 16384,
    }
    config = {
        "INPUT_TOKENS": 250000,
        "CONTEXT_WINDOW": 1000000,
        "PERPLEXITY_INPUT_TOKENS": 111000,
        "PERPLEXITY_CONTEXT_WINDOW": 128000,
        "PERPLEXITY_OUTPUT_TOKENS": 100,
    }

    resolved = _perplexity_service_config(deps, config, "perplexity/sonar")

    assert resolved.input_tokens == 111000
    assert resolved.context_window == 128000


def test_perplexity_budget_warning_names_the_key_that_supplied_the_value():
    """A shared cap must be named as the shared key, not as the Sonar default."""
    from src.message_processor import _perplexity_service_config
    from src.providers.perplexity import AgentResponsesProvider

    deps = {"SYSTEM_MESSAGE": "System prompt", "OUTPUT_TOKENS": 16384}
    config = {
        "INPUT_TOKENS": 5000,
        "CONTEXT_WINDOW": 15000,
        "PERPLEXITY_INPUT_TOKENS": 111000,
        "PERPLEXITY_CONTEXT_WINDOW": 128000,
        "PERPLEXITY_OUTPUT_TOKENS": 12000,
    }
    resolved = _perplexity_service_config(deps, config, "perplexity/sonar")
    logger = MagicMock()
    provider = AgentResponsesProvider(MagicMock(), resolved, logger=logger)

    provider.build_request("System prompt", CURRENT, None, 12000, logger=logger)

    warning_text = " ".join(
        str(argument) for call in logger.warning.call_args_list for argument in call.args
    )
    assert "INPUT_TOKENS 5000" in warning_text
    assert "CONTEXT_WINDOW 15000" in warning_text
    assert "PERPLEXITY_OUTPUT_TOKENS 12000" in warning_text
    assert "PERPLEXITY_INPUT_TOKENS" not in warning_text
    assert "PERPLEXITY_CONTEXT_WINDOW" not in warning_text


def test_perplexity_defaults_fit_the_sonar_context_window():
    """The Perplexity path budgets for Sonar's documented 128K window."""
    from src.models import PerplexityConfig

    config = PerplexityConfig()

    assert config.context_window == 128000
    assert config.input_tokens == 111000
    assert config.input_tokens + config.output_tokens <= config.context_window


@pytest.mark.asyncio
async def test_perplexity_prompt_budget_charges_the_fetch_url_suffix():
    """The fixed instruction suffix is part of the prompt, not free extra text."""
    from src.models import PerplexityConfig
    from src.providers.perplexity import (
        FETCH_URL_INSTRUCTIONS,
        AgentResponsesProvider,
    )

    client = RecordingClient()
    config = PerplexityConfig(
        output_tokens=100,
        input_tokens=500,
        context_window=200000,
    )
    provider = AgentResponsesProvider(client, config)

    request = provider.build_request("System prompt", "Z" * 5000, [], 100)

    assert FETCH_URL_INSTRUCTIONS in request.messages[0]["content"]
    assert estimate_messages_tokens(request.messages) <= config.input_tokens
    assert request.max_output_tokens == 100


def test_perplexity_budget_warning_names_the_perplexity_settings():
    """The conflict warning must not point an operator at the chat keys."""
    from src.providers.perplexity import AgentResponsesProvider

    logger = MagicMock()
    provider = AgentResponsesProvider(MagicMock(), logger=logger)

    provider.build_request(
        "System prompt",
        CURRENT,
        None,
        100,
        input_tokens=8000,
        output_tokens=5000,
        context_window=9000,
        logger=logger,
    )

    warning_text = " ".join(
        str(argument) for call in logger.warning.call_args_list for argument in call.args
    )
    assert "PERPLEXITY_INPUT_TOKENS" in warning_text
    assert "PERPLEXITY_OUTPUT_TOKENS" in warning_text
    assert "PERPLEXITY_CONTEXT_WINDOW" in warning_text
    assert " INPUT_TOKENS " not in warning_text


def test_script_aware_estimate_keeps_english_within_two_percent():
    """ASCII prose stays on the historical four-characters-per-token estimate."""
    from math import ceil

    from src.message_builder import estimate_text_tokens

    english = ("The quick brown fox jumps over the lazy dog. " * 50)[:2000]
    old_estimate = ceil(len(english) * 1.1 / 4)
    new_estimate = estimate_text_tokens(english)

    assert abs(new_estimate - old_estimate) <= 0.02 * old_estimate
    assert 500 <= new_estimate <= 560


@pytest.mark.parametrize(
    ("sample", "low", "high"),
    [
        ("é" * 2000, 0.53, 0.56),
        ("あ" * 2000, 0.86, 0.90),
        ("漢" * 2000, 0.86, 0.90),
        ("ह" * 2000, 0.86, 0.90),
        ("한" * 2000, 0.86, 0.90),
        ("🙂" * 2000, 1.84, 1.90),
    ],
)
def test_script_aware_estimate_ratios(sample, low, high):
    """Each script's estimate per character sits in its fixed absolute range."""
    from src.message_builder import estimate_text_tokens

    ratio = estimate_text_tokens(sample) / len(sample)
    assert low <= ratio <= high


def test_japanese_history_is_trimmed_to_the_budget():
    """A Japanese history is counted with its real script weight and trimmed."""
    history = []
    for index in range(80):
        history.append({"role": "user", "content": f"質問{index:03d} " + "あ" * 120})
        history.append({"role": "assistant", "content": f"回答{index:03d} " + "い" * 120})

    messages = build_messages(
        "システム",
        "最新の質問です",
        history,
        input_tokens=600,
        output_tokens=50,
        context_window=200000,
    )

    joined = "\n".join(str(message["content"]) for message in messages)
    assert "質問000" not in joined
    assert "質問079" in joined
    assert messages[-1] == {"role": "user", "content": "最新の質問です"}
    assert estimate_messages_tokens(messages) <= 600
