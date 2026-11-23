"""Tests for the bounded web-tool loop on the Ollama chat path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import OpenAIConfig
from src.openai_processing import process_openai_message


def _tool_call(call_id="call-1", name="web_search", arguments='{"query":"news"}'):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content="", finish_reason="stop", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class _ChatClient:
    def __init__(self, base_url, responses, api_key="ollama-key"):
        self.base_url = base_url
        self.api_key = api_key
        self.calls = []
        self._responses = list(responses)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


async def _run(make_request, client, *, config=None, logger=None):
    return await process_openai_message(
        request=make_request(
            "What happened today?",
            conversation_manager=MagicMock(),
            logger=logger or MagicMock(),
        ),
        conversation_summary=[],
        openai_client=client,
        config=config or OpenAIConfig(),
    )


@pytest.mark.asyncio
async def test_tool_call_is_executed_and_final_answer_is_returned(make_request, monkeypatch):
    """A tool_calls response is completed with a tool message, then answered."""
    tool_result = '{"results":[{"title":"News","url":"https://example.com"}]}'
    tool = AsyncMock(return_value=tool_result)
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    logger = MagicMock()
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response("Final answer."),
        ],
    )

    result = await _run(make_request, client, logger=logger)

    assert result == "Final answer."
    assert len(client.calls) == 2
    assert client.calls[0]["tools"]
    sent_messages = client.calls[1]["messages"]
    assert sent_messages[-2]["role"] == "assistant"
    assert sent_messages[-2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert sent_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": tool_result,
    }
    tool.assert_awaited_once()
    assert tool.await_args.kwargs["api_key"] == "ollama-key"
    assert tool.await_args.kwargs["base_url"] == "https://ollama.com/v1/"
    assert any(
        call.args[0] == "web_tool=%s ok=%s" and call.args[1:] == ("web_search", "true")
        for call in logger.info.call_args_list
    )


@pytest.mark.asyncio
async def test_tool_failure_still_returns_the_model_answer(make_request, monkeypatch):
    """A failed tool is fed back to the model and does not fail the request."""
    monkeypatch.setattr(
        "src.openai_processing.call_web_tool",
        AsyncMock(return_value='{"error":"ConnectError: boom","tool":"web_search"}'),
    )
    logger = MagicMock()
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response("Answer without search results."),
        ],
    )

    result = await _run(make_request, client, logger=logger)

    assert result == "Answer without search results."
    assert any(
        call.args[0] == "web_tool=%s ok=%s" and call.args[1:] == ("web_search", "false")
        for call in logger.info.call_args_list
    )


@pytest.mark.asyncio
async def test_bad_tool_arguments_are_fed_back_without_execution(make_request, monkeypatch):
    """Malformed model arguments become an error tool result."""
    tool = AsyncMock()
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(
                finish_reason="tool_calls",
                tool_calls=[_tool_call(arguments="{not json")],
            ),
            _response("Recovered."),
        ],
    )

    result = await _run(make_request, client)

    assert result == "Recovered."
    tool.assert_not_awaited()
    assert client.calls[1]["messages"][-1]["content"] == '{"error":"bad arguments"}'


@pytest.mark.asyncio
async def test_tool_loop_stops_after_four_rounds(make_request, monkeypatch):
    """A model that keeps asking for tools cannot loop forever."""
    tool = AsyncMock(return_value='{"results":[]}')
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    client = _ChatClient(
        "https://ollama.com/v1/",
        [_response(finish_reason="tool_calls", tool_calls=[_tool_call()]) for _ in range(4)],
    )

    result = await _run(make_request, client)

    assert result is None
    assert len(client.calls) == 4
    assert "tools" not in client.calls[-1]
    assert tool.await_count == 3


@pytest.mark.asyncio
async def test_tools_are_not_attached_for_openai(make_request):
    """OpenAI would reject Ollama's tool endpoints, so no tools are sent."""
    client = _ChatClient("https://api.openai.com/v1/", [_response("Plain answer.")])

    result = await _run(make_request, client)

    assert result == "Plain answer."
    assert "tools" not in client.calls[0]


@pytest.mark.asyncio
async def test_tools_are_not_attached_when_disabled(make_request):
    """The WEB_TOOLS switch disables offering regardless of the provider."""
    client = _ChatClient("https://ollama.com/v1/", [_response("Plain answer.")])

    result = await _run(
        make_request,
        client,
        config=OpenAIConfig(web_tools=False),
    )

    assert result == "Plain answer."
    assert "tools" not in client.calls[0]


@pytest.mark.asyncio
async def test_final_tool_round_answers_without_tools(make_request, monkeypatch):
    """The fourth round is offered no tools and its answer is returned."""
    tool = AsyncMock(return_value='{"results":[]}')
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response("Answered on the last round."),
        ],
    )

    result = await _run(make_request, client)

    assert result == "Answered on the last round."
    assert len(client.calls) == 4
    assert all("tools" in call for call in client.calls[:3])
    assert "tools" not in client.calls[-1]
    assert tool.await_count == 3


@pytest.mark.asyncio
async def test_tool_calls_per_round_are_capped(make_request, monkeypatch):
    """Extra tool calls in one round are answered without being executed."""
    tool = AsyncMock(return_value='{"results":[]}')
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    calls = [_tool_call(f"call-{index}") for index in range(5)]
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(finish_reason="tool_calls", tool_calls=calls),
            _response("Done."),
        ],
    )

    result = await _run(make_request, client)

    assert result == "Done."
    assert tool.await_count == 3
    tool_messages = [
        message for message in client.calls[1]["messages"] if message["role"] == "tool"
    ]
    assert len(tool_messages) == 5
    assert tool_messages[3]["content"] == '{"error":"tool-call limit reached"}'
    assert tool_messages[4]["content"] == '{"error":"tool-call limit reached"}'


@pytest.mark.asyncio
async def test_tool_output_budget_feeds_back_a_short_result(make_request, monkeypatch):
    """A result over the output budget becomes a short budget notice."""
    oversized = '{"results":["' + "x" * 60000 + '"]}'
    tool = AsyncMock(return_value=oversized)
    monkeypatch.setattr("src.openai_processing.call_web_tool", tool)
    client = _ChatClient(
        "https://ollama.com/v1/",
        [
            _response(finish_reason="tool_calls", tool_calls=[_tool_call()]),
            _response("Answered without the oversized result."),
        ],
    )

    result = await _run(make_request, client)

    assert result == "Answered without the oversized result."
    tool.assert_awaited_once()
    tool_message = client.calls[1]["messages"][-1]
    assert tool_message == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"error":"tool-output budget reached"}',
    }
