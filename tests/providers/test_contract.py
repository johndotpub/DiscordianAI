"""Contract tests shared by the chat-completions and Agent adapters."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from src.error_handling import (
    CircuitBreakerOpenError,
    ErrorType,
    classify_error,
    get_circuit_breaker,
)
from src.health_checks import PROVIDER_HEALTH_SPECS
from src.health_server import PROVIDER_NAMES
from src.models import AIRequest, OpenAIConfig, PerplexityConfig
from src.openai_processing import process_openai_message
from src.perplexity_processing import process_perplexity_message
from src.providers.openai_chat import ChatCompletionsProvider
from src.providers.perplexity import AgentResponsesProvider
from src.providers.registry import PROVIDERS, get

URL_ONE = "https://search.example/one"


def _chat_response(text="Answer", *, finish_reason="stop", tool_calls=None):
    message = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def _tool_call(call_id="call-1", name="web_search", arguments='{"query":"news"}'):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _agent_response(text="Answer [1]", results=None):
    output = []
    if results is not None:
        output.append({"type": "search_results", "results": results})
    output.append(
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }
    )
    return {"output": output}


def _request(message="Question", user_id=12345):
    return AIRequest(
        message=message,
        user=SimpleNamespace(id=user_id),
        conversation_manager=MagicMock(),
        logger=logging.getLogger("provider-contract"),
    )


class FakeChatClient:
    """Stub AsyncOpenAI-shaped chat client that records call parameters."""

    def __init__(self, responses, *, base_url="https://ollama.com/v1", api_key="key"):
        self.base_url = base_url
        self.api_key = api_key
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        self.models = SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="model")]))
        )

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FailingChatClient:
    """Stub chat client that always raises the supplied exception."""

    def __init__(self, error, *, base_url="https://ollama.com/v1"):
        self.base_url = base_url
        self.api_key = "key"
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        self.models = SimpleNamespace(list=AsyncMock(side_effect=error))

    async def _create(self, **_kwargs):
        self.calls.append(1)
        raise self.error


class FakeResponsesClient:
    """Stub Perplexity Agent API client that records call parameters."""

    def __init__(self, responses, *, base_url="https://api.perplexity.ai/v1"):
        self.base_url = base_url
        self.api_key = "key"
        self.responses_list = list(responses)
        self.calls = []
        self.responses = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="model")]))
        )

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses_list.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FailingResponsesClient:
    """Stub Agent client that always raises the supplied exception."""

    def __init__(self, error, *, base_url="https://api.perplexity.ai/v1"):
        self.base_url = base_url
        self.responses = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(list=AsyncMock(side_effect=error))
        self.error = error
        self.calls = []

    async def _create(self, **_kwargs):
        self.calls.append(1)
        raise self.error


def _openai_config(**overrides):
    values = {
        "model": "test-model",
        "system_message": "You are helpful.",
        "output_tokens": 100,
        "input_tokens": 1000,
        "context_window": 8000,
        "web_tools": True,
    }
    values.update(overrides)
    return OpenAIConfig(**values)


def _perplexity_config(**overrides):
    values = {
        "model": "perplexity/sonar",
        "system_message": "Answer with sources.",
        "output_tokens": 100,
        "input_tokens": 1000,
        "context_window": 8000,
    }
    values.update(overrides)
    return PerplexityConfig(**values)


@pytest.mark.parametrize(
    ("base_url", "cap_key", "tools_expected"),
    [
        ("https://ollama.com/v1", "max_tokens", True),
        ("https://api.openai.com/v1", "max_completion_tokens", False),
    ],
)
@pytest.mark.asyncio
async def test_chat_request_shape(base_url, cap_key, tools_expected):
    client = FakeChatClient([_chat_response("Hello")], base_url=base_url)
    provider = ChatCompletionsProvider(client, _openai_config())

    request = provider.build_request("System prompt", "Current question", [], 100)
    result = await provider.complete(request)

    params = client.calls[0]
    assert params["model"] == "test-model"
    assert params[cap_key] == 100
    other_key = "max_tokens" if cap_key == "max_completion_tokens" else "max_completion_tokens"
    assert other_key not in params
    assert params["messages"][0] == {"role": "system", "content": "System prompt"}
    assert params["messages"][-1] == {"role": "user", "content": "Current question"}
    assert ("tools" in params) is tools_expected
    assert result.text == "Hello"
    assert dict(result.citations) == {}
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_invalid_response_body_is_not_logged(caplog):
    """An invalid chat response is logged by type and id, not by body."""
    canary = "PROVIDER-BODY-CANARY-987654"
    response = SimpleNamespace(choices=[], body=canary, id="resp-1")
    client = FakeChatClient([response])
    logger = logging.getLogger("provider-invalid-response")
    provider = ChatCompletionsProvider(client, _openai_config(), logger=logger)
    request = provider.build_request("System prompt", "Current question", [], 100)

    with caplog.at_level(logging.ERROR, logger=logger.name):
        with pytest.raises(ValueError, match="no choices"):
            await provider.complete(request)

    assert canary not in caplog.text
    assert "id=resp-1" in caplog.text


@pytest.mark.asyncio
async def test_perplexity_request_shape_and_citations():
    client = FakeResponsesClient(
        [_agent_response("The report says [1].", [{"id": 1, "url": URL_ONE}])]
    )
    provider = AgentResponsesProvider(client, _perplexity_config())
    history = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]

    request = provider.build_request("System prompt", "Current question", history, 100)
    result = await provider.complete(request)

    params = client.calls[0]
    assert params["model"] == "perplexity/sonar"
    assert params["instructions"].startswith("System prompt")
    assert "fetch_url" in params["instructions"]
    assert params["input"] == [
        *history,
        {"role": "user", "content": "Current question"},
    ]
    assert params["max_output_tokens"] == 100
    assert params["tools"] == [{"type": "web_search"}, {"type": "fetch_url"}]
    assert params["extra_body"]["max_steps"] == 4
    assert "max_steps" not in params
    assert "messages" not in params
    assert result.text == "The report says [1]."
    assert dict(result.citations) == {"1": URL_ONE}
    assert result.finish_reason is None


@pytest.mark.asyncio
async def test_chat_length_finish_reason_is_reported():
    """A chat answer stopped by the output cap reports the length reason."""
    client = FakeChatClient([_chat_response("A partial answer", finish_reason="length")])
    provider = ChatCompletionsProvider(client, _openai_config())

    request = provider.build_request("System prompt", "Current question", [], 100)
    result = await provider.complete(request)

    assert result.text == "A partial answer"
    assert result.finish_reason == "length"


@pytest.mark.asyncio
async def test_agent_incomplete_max_output_tokens_is_normalised_to_length():
    """The Agent API's incomplete output-cap status becomes a length reason."""
    response = _agent_response("A partial answer [1]", [{"id": 1, "url": URL_ONE}])
    response["status"] = "incomplete"
    response["incomplete_details"] = {"reason": "max_output_tokens"}
    client = FakeResponsesClient([response])
    provider = AgentResponsesProvider(client, _perplexity_config())

    request = provider.build_request("System prompt", "Current question", [], 100)
    result = await provider.complete(request)

    assert result.text == "A partial answer [1]"
    assert result.finish_reason == "length"


@pytest.mark.asyncio
async def test_agent_other_incomplete_reason_is_not_reported_as_length():
    """An incomplete response for another reason must not claim a length cap."""
    response = _agent_response("A filtered answer")
    response["status"] = "incomplete"
    response["incomplete_details"] = {"reason": "content_filter"}
    client = FakeResponsesClient([response])
    provider = AgentResponsesProvider(client, _perplexity_config())

    request = provider.build_request("System prompt", "Current question", [], 100)
    result = await provider.complete(request)

    assert result.finish_reason is None


@pytest.mark.asyncio
async def test_chat_tool_loop_round_trip():
    executor = AsyncMock(return_value='{"results":[]}')
    client = FakeChatClient(
        [
            _chat_response("", finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _chat_response("Final answer"),
        ]
    )
    provider = ChatCompletionsProvider(
        client,
        _openai_config(),
        tool_executor=executor,
    )

    request = provider.build_request("System", "Question", [], 100)
    result = await provider.complete(request)

    assert result.text == "Final answer"
    assert len(client.calls) == 2
    executor.assert_awaited_once()
    assert executor.await_args.kwargs["api_key"] == "key"
    assert executor.await_args.kwargs["base_url"] == "https://ollama.com/v1"
    sent_messages = client.calls[1]["messages"]
    assert sent_messages[-2] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query":"news"}'},
            }
        ],
    }
    assert sent_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"results":[]}',
    }


@pytest.mark.asyncio
async def test_chat_tool_loop_stops_at_the_round_cap():
    executor = AsyncMock(return_value='{"results":[]}')
    client = FakeChatClient(
        [
            _chat_response("", finish_reason="tool_calls", tool_calls=[_tool_call()])
            for _ in range(4)
        ]
    )
    provider = ChatCompletionsProvider(
        client,
        _openai_config(),
        tool_executor=executor,
    )

    request = provider.build_request("System", "Question", [], 100)
    result = await provider.complete(request)

    assert result.text == ""
    assert result.finish_reason == "tool_calls"
    assert len(client.calls) == 4
    assert "tools" not in client.calls[-1]
    assert executor.await_count == 3


def _status_response(status_code):
    return SimpleNamespace(status_code=status_code, headers={}, request=SimpleNamespace())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            openai.InternalServerError("server error", response=_status_response(500), body=None),
            ErrorType.API_SERVER_ERROR,
        ),
        (
            openai.RateLimitError("rate limit", response=_status_response(429), body=None),
            ErrorType.API_RATE_LIMIT,
        ),
        (
            openai.APITimeoutError(request=SimpleNamespace()),
            ErrorType.API_TIMEOUT,
        ),
        (
            openai.APIConnectionError(message="transport problem", request=SimpleNamespace()),
            ErrorType.NETWORK_ERROR,
        ),
    ],
)
def test_provider_errors_keep_their_classification(error, expected):
    assert classify_error(error).error_type == expected


@pytest.mark.parametrize(
    ("provider_name", "client_factory", "provider_factory", "config"),
    [
        (
            "openai",
            FailingChatClient,
            ChatCompletionsProvider,
            _openai_config(),
        ),
        (
            "perplexity",
            FailingResponsesClient,
            AgentResponsesProvider,
            _perplexity_config(),
        ),
    ],
)
@pytest.mark.asyncio
async def test_breaker_opens_after_threshold(
    provider_name, client_factory, provider_factory, config
):
    breaker = get_circuit_breaker(provider_name)
    error = openai.InternalServerError(
        "provider is down", response=_status_response(500), body=None
    )
    client = client_factory(error)
    provider = provider_factory(client, config)
    request = provider.build_request("System", "Question", [], 100)

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        for _ in range(5):
            with pytest.raises(openai.InternalServerError):
                await provider.complete(request)

    assert breaker.state == "OPEN"
    assert breaker.failure_count == 5

    client.calls.clear()
    with pytest.raises(CircuitBreakerOpenError):
        await provider.complete(request)
    assert client.calls == []


@pytest.mark.parametrize(
    ("client_factory", "provider_factory", "config"),
    [
        (FakeChatClient, ChatCompletionsProvider, _openai_config()),
        (FakeResponsesClient, AgentResponsesProvider, _perplexity_config()),
    ],
)
@pytest.mark.asyncio
async def test_probe_reports_success_and_failure(client_factory, provider_factory, config):
    healthy = provider_factory(client_factory([]), config)

    result = await healthy.probe()

    assert result.ok is True
    assert "1 models" in result.detail

    failing_client = client_factory([])
    failing_client.models.list = AsyncMock(side_effect=RuntimeError("down"))
    failing = provider_factory(failing_client, config)

    result = await failing.probe()

    assert result.ok is False
    assert "RuntimeError" in result.detail


@pytest.mark.asyncio
async def test_identical_openai_calls_hit_the_cache():
    client = FakeChatClient([_chat_response("A cacheable answer")])
    request = _request("cache me")

    first = await process_openai_message(request, [], client, _openai_config())
    second = await process_openai_message(request, [], client, _openai_config())

    assert first == second == "A cacheable answer"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_identical_perplexity_calls_hit_the_cache():
    client = FakeResponsesClient([_agent_response("A cacheable web answer.")])
    request = _request("cache me")

    first = await process_perplexity_message(request, client, _perplexity_config())
    second = await process_perplexity_message(request, client, _perplexity_config())

    assert first == second
    assert first is not None
    assert first[0] == "A cacheable web answer."
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_truncated_openai_answer_is_not_cached():
    """A partial answer stopped at the output cap is fetched again."""
    client = FakeChatClient(
        [
            _chat_response("A partial answer", finish_reason="length"),
            _chat_response("A fresh answer"),
        ]
    )
    request = _request("cache me")

    first = await process_openai_message(request, [], client, _openai_config())
    second = await process_openai_message(request, [], client, _openai_config())

    assert first == "A partial answer"
    assert second == "A fresh answer"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_truncated_perplexity_answer_is_not_cached():
    """An incomplete Agent response is not replayed from the cache."""
    partial = _agent_response("A partial web answer.")
    partial["status"] = "incomplete"
    partial["incomplete_details"] = {"reason": "max_output_tokens"}
    client = FakeResponsesClient([partial, _agent_response("A fresh web answer.")])
    request = _request("cache me")

    first = await process_perplexity_message(request, client, _perplexity_config())
    second = await process_perplexity_message(request, client, _perplexity_config())

    assert first is not None
    assert first[0] == "A partial web answer."
    assert second is not None
    assert second[0] == "A fresh web answer."
    assert len(client.calls) == 2


def test_registry_is_the_single_source_for_provider_wiring():
    assert tuple(PROVIDERS) == ("openai", "perplexity")
    assert get("openai").config_type is OpenAIConfig
    assert get("perplexity").config_type is PerplexityConfig
    assert all(spec.health and spec.breaker for spec in PROVIDERS.values())
    assert tuple(PROVIDER_HEALTH_SPECS) == (*PROVIDERS, "discord")
    assert tuple(PROVIDERS) == PROVIDER_NAMES

    pool = MagicMock()
    pool.create_openai_client.return_value = "openai-client"
    pool.create_perplexity_client.return_value = "perplexity-client"

    assert get("openai").client_factory(pool, "key", "https://example/v1") == "openai-client"
    assert (
        get("perplexity").client_factory(pool, "key", "https://example/v1") == "perplexity-client"
    )
    pool.create_openai_client.assert_called_once_with("key", "https://example/v1", None)
    pool.create_perplexity_client.assert_called_once_with("key", "https://example/v1", None)
