"""Vision plumbing: attachment policy through request, routing, cache, and history."""

import base64
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.caching import _cache_context, _generate_scoped_key
from src.config import ERROR_MESSAGES, load_config
from src.image_attachments import ImagePayload
from src.message_builder import build_messages, estimate_message_tokens
from src.message_processor import _process_message_core
from src.models import AIClients, AIConfig, AIRequest, OpenAIConfig, PerplexityConfig
from src.openai_processing import process_openai_message
from src.routing.contracts import RouteDecision
from src.smart_orchestrator import (
    _history_user_text,
    _record_conversation_turn,
    _vision_decision,
    get_smart_response,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"tiny-png"
VISION_ENV_KEYS = (
    "VISION_ENABLED",
    "VISION_MAX_IMAGES",
    "VISION_MAX_BYTES",
    "VISION_TOKEN_ESTIMATE",
)


def _payload(data=PNG, *, filename="picture.png", mime="image/png") -> ImagePayload:
    return ImagePayload(
        filename=filename,
        mime=mime,
        data_b64=base64.b64encode(data).decode("ascii"),
        width=8,
        height=8,
    )


def _request(message="Describe this.", *, images=(), conversation_key="g:1:c:2"):
    return AIRequest(
        message=message,
        user=SimpleNamespace(id=12345),
        conversation_manager=MagicMock(),
        logger=MagicMock(),
        conversation_key=conversation_key,
        images=tuple(images),
    )


def _config(**overrides):
    values = {
        "model": "test-model",
        "system_message": "You are helpful.",
        "output_tokens": 100,
        "input_tokens": 10000,
        "context_window": 1000000,
        "web_tools": False,
    }
    values.update(overrides)
    return OpenAIConfig(**values)


def _ai_config():
    return AIConfig(
        openai=_config(),
        perplexity=PerplexityConfig(
            model="perplexity/sonar",
            system_message="You are helpful.",
            output_tokens=100,
            input_tokens=10000,
            context_window=1000000,
        ),
    )


class FakeChatClient:
    """Minimal AsyncOpenAI-shaped client recording each create call."""

    def __init__(self, text="I can see the image."):
        self.base_url = "https://ollama.com/v1"
        self.api_key = "key"
        self.calls = []
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=text),
                    finish_reason="stop",
                )
            ]
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        self._response = response

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeAttachment:
    """Discord attachment double used by the message-processor tests."""

    def __init__(self, data=PNG, *, filename="picture.png"):
        self.filename = filename
        self.content_type = "image/png"
        self.size = len(data)
        self.width = 8
        self.height = 8
        self._data = data
        self.read = AsyncMock(return_value=data)


def test_build_messages_places_a_text_part_then_image_parts():
    first = _payload(filename="one.png")
    second = _payload(b"\xff\xd8\xffjpeg", filename="two.jpg", mime="image/jpeg")

    messages = build_messages("System.", "What is shown?", images=[first, second])

    assert messages[-1] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "What is shown?"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{first.data_b64}"},
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{second.data_b64}"},
            },
        ],
    }


def test_image_only_message_keeps_an_empty_text_part():
    image = _payload()

    messages = build_messages("System.", "", images=[image])

    content = messages[-1]["content"]
    assert content[0] == {"type": "text", "text": ""}
    assert len(content) == 2


def test_image_payload_length_is_not_counted_as_text():
    small = _payload(b"a")
    large = _payload(b"a" * 40000)

    small_message = build_messages("System.", "Look.", images=[small])[-1]
    large_message = build_messages("System.", "Look.", images=[large])[-1]
    text_only = {"role": "user", "content": "Look."}

    assert estimate_message_tokens(small_message) == estimate_message_tokens(large_message)
    assert estimate_message_tokens(large_message) - estimate_message_tokens(text_only) == 1000


def test_truncation_drops_history_but_keeps_the_image_part():
    image = _payload()
    history = [
        {"role": "user", "content": "Q" * 20000},
        {"role": "assistant", "content": "A" * 20000},
    ]

    messages = build_messages(
        "System prompt.",
        "Describe.",
        history,
        input_tokens=500,
        output_tokens=100,
        context_window=100000,
        images=[image],
    )

    assert isinstance(messages[-1]["content"], list)
    assert messages[-1]["content"][1]["type"] == "image_url"
    assert messages[-1]["content"][1]["image_url"]["url"].endswith(image.data_b64)
    assert all(isinstance(message["content"], str) for message in messages[1:-1])


def test_cache_key_changes_when_only_the_image_changes():
    same_text_different_image = _request(images=[_payload(b"one")])
    identical = _request(images=[_payload(b"one")])
    other_image = _request(images=[_payload(b"two")])

    def key(request):
        message, context, salt = _cache_context("process_openai", (request,), {})
        return _generate_scoped_key(message, context, salt=salt)

    assert key(same_text_different_image) == key(identical)
    assert key(same_text_different_image) != key(other_image)
    assert key(same_text_different_image) != key(_request())


def test_history_stores_image_labels_not_payloads():
    manager = MagicMock()
    request = _request(
        "What is this?",
        images=[_payload(filename="cat.png")],
    )
    request = AIRequest(
        message=request.message,
        user=request.user,
        conversation_manager=manager,
        logger=request.logger,
        conversation_key=request.conversation_key,
        images=request.images,
    )

    _record_conversation_turn(request, "A cat.", "openai", "test-model")

    manager.add_message.assert_any_call(
        "g:1:c:2",
        "user",
        "[image: cat.png] What is this?",
    )
    stored_text = manager.add_message.call_args_list[0].args[2]
    assert request.images[0].data_b64 not in stored_text


def test_image_only_history_label_uses_the_filename_or_placeholder():
    assert _history_user_text(_request("", images=[_payload(filename="")])) == "[image]"
    assert _history_user_text(_request("", images=[_payload(filename="a.png")])) == (
        "[image: a.png]"
    )


def test_vision_decision_forces_the_local_route():
    decision = RouteDecision(
        route="web",
        reasons=("bearing:time.deixis",),
        text="What is the price today?",
    )

    forced = _vision_decision(decision)

    assert forced.route == "local"
    assert forced.reasons == ("images:local",)
    assert forced.text == decision.text


@pytest.mark.asyncio
async def test_hybrid_image_request_never_calls_perplexity():
    openai_client = FakeChatClient()
    perplexity_create = AsyncMock()
    perplexity_client = SimpleNamespace(
        responses=SimpleNamespace(create=perplexity_create),
        models=SimpleNamespace(list=AsyncMock()),
    )
    request = _request(
        "What is the current price of bitcoin in this picture?",
        images=[_payload()],
    )

    response = await get_smart_response(
        request,
        [],
        AIClients(openai=openai_client, perplexity=perplexity_client),
        _ai_config(),
        {"ROUTER_MODE": "heuristic"},
    )

    assert response[0] == "I can see the image."
    perplexity_create.assert_not_awaited()
    assert len(openai_client.calls) == 1
    assert openai_client.calls[0]["messages"][-1]["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_openai_processing_forwards_request_images():
    client = FakeChatClient()

    result = await process_openai_message(
        _request(images=[_payload()]),
        [],
        client,
        _config(),
    )

    assert result == "I can see the image."
    content = client.calls[0]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "Describe this."}
    assert content[1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_openai_cache_keeps_different_images_apart():
    client = FakeChatClient()

    await process_openai_message(
        _request("same", images=[_payload(b"one")]), [], client, _config()
    )
    await process_openai_message(
        _request("same", images=[_payload(b"two")]), [], client, _config()
    )
    await process_openai_message(
        _request("same", images=[_payload(b"one")]), [], client, _config()
    )

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_perplexity_only_mode_refuses_an_image_request():
    perplexity_create = AsyncMock()
    perplexity_client = SimpleNamespace(
        responses=SimpleNamespace(create=perplexity_create),
    )

    response = await get_smart_response(
        _request(images=[_payload()]),
        [],
        AIClients(openai=None, perplexity=perplexity_client),
        _ai_config(),
        {},
    )

    assert response[0] == ERROR_MESSAGES["vision_unavailable"]
    perplexity_create.assert_not_awaited()


def _deps(config):
    manager = MagicMock()
    manager.get_conversation_summary_formatted.return_value = []
    return {
        "logger": logging.getLogger("vision-test"),
        "rate_limiter": MagicMock(),
        "conversation_manager": manager,
        "client": None,
        "perplexity_client": None,
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "GPT_MODEL": "test-model",
        "REASONING_EFFORT": "high",
        "PERPLEXITY_MODEL": "perplexity/sonar",
        "SYSTEM_MESSAGE": "System.",
        "OUTPUT_TOKENS": 100,
        "PERPLEXITY_OUTPUT_TOKENS": 100,
        "INPUT_TOKENS": 10000,
        "CONTEXT_WINDOW": 1000000,
        "config": config,
    }


def _message(attachments, content=""):
    return SimpleNamespace(
        id=1,
        author=SimpleNamespace(id=7, name="user", mention="<@7>", bot=False),
        channel=SimpleNamespace(id=2, send=AsyncMock()),
        guild=None,
        content=content,
        attachments=attachments,
    )


@pytest.mark.asyncio
async def test_image_only_message_without_text_is_processed():
    message = _message([FakeAttachment()], content="")
    deps = _deps({})
    response = AsyncMock(return_value=("answer", False, None))

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", response),
        patch("src.message_processor.send_formatted_message", AsyncMock()),
    ):
        await _process_message_core(message, deps, is_dm=True)

    request = response.call_args.args[0]
    assert len(request.images) == 1
    assert request.images[0].filename == "picture.png"
    ai_config = response.call_args.args[3]
    assert ai_config.openai.vision_token_estimate == 1000
    message.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_vision_ignores_attachments_and_keeps_the_empty_reply():
    attachment = FakeAttachment()
    message = _message([attachment], content="")
    deps = _deps({"VISION_ENABLED": False})
    response = AsyncMock()

    with (
        patch("src.message_processor.check_rate_limit", AsyncMock(return_value=True)),
        patch("src.message_processor.get_smart_response", response),
    ):
        await _process_message_core(message, deps, is_dm=True)

    response.assert_not_awaited()
    attachment.read.assert_not_awaited()
    message.channel.send.assert_awaited_once()
    assert "generating a response" in message.channel.send.call_args.args[0]


def test_vision_config_defaults_and_environment_overrides(monkeypatch):
    for key in VISION_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    defaults = load_config()

    assert defaults["VISION_ENABLED"] is True
    assert defaults["VISION_MAX_IMAGES"] == 4
    assert defaults["VISION_MAX_BYTES"] == 5242880
    assert defaults["VISION_TOKEN_ESTIMATE"] == 1000

    monkeypatch.setenv("VISION_ENABLED", "false")
    monkeypatch.setenv("VISION_MAX_IMAGES", "2")
    monkeypatch.setenv("VISION_MAX_BYTES", "1024")
    monkeypatch.setenv("VISION_TOKEN_ESTIMATE", "250")

    overridden = load_config()

    assert overridden["VISION_ENABLED"] is False
    assert overridden["VISION_MAX_IMAGES"] == 2
    assert overridden["VISION_MAX_BYTES"] == 1024
    assert overridden["VISION_TOKEN_ESTIMATE"] == 250
