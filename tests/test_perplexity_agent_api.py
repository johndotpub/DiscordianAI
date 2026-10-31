"""Regression tests for the Perplexity Agent API path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from src.api_validation import validate_perplexity_config
from src.config import DEFAULT_PERPLEXITY_MODEL
from src.connection_pool import versioned_perplexity_client
from src.error_handling import ErrorType, classify_error
from src.health_checks import APIHealthMonitor
from src.models import AIRequest, PerplexityConfig
from src.perplexity_processing import _parse_agent_response, process_perplexity_message

URL_ONE = "https://search.example/one"
URL_TWO = "https://search.example/two"


def _message_item(text: str) -> dict:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def _search_item(results: list[dict]) -> dict:
    return {"type": "search_results", "results": results}


def _request(message: str = "What is the latest news?") -> AIRequest:
    return AIRequest(
        message=message,
        user=MagicMock(id=12345),
        conversation_manager=MagicMock(),
        logger=MagicMock(),
    )


class RecordingResponsesClient:
    """Fake client exposing only the Agent API Responses resource."""

    def __init__(self, response: dict):
        self.responses = SimpleNamespace(create=AsyncMock(return_value=response))


class VersionedClient(RecordingResponsesClient):
    """Fake SDK client that records the base URL used by ``with_options``."""

    base_url = "https://api.perplexity.ai"

    def __init__(self, response: dict):
        super().__init__(response)
        self.versioned_base_url: str | None = None

    def with_options(self, *, base_url: str):
        self.versioned_base_url = base_url
        return self


class VersionedModelsClient:
    """Fake SDK client for the health check's model listing call."""

    base_url = "https://api.perplexity.ai"

    def __init__(self, model_id: str):
        self.versioned_base_url: str | None = None
        self.models = SimpleNamespace(
            list=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id=model_id)]))
        )

    def with_options(self, *, base_url: str):
        self.versioned_base_url = base_url
        return self


def _api_error(
    exception_type: type[Exception],
    status_code: int,
    message: str,
) -> Exception:
    return exception_type(
        message,
        response=SimpleNamespace(
            status_code=status_code,
            headers={},
            request=SimpleNamespace(),
        ),
        body=None,
    )


@pytest.mark.asyncio
async def test_request_uses_agent_api_fields_and_web_search_tool():
    response = {"output": [_message_item("A current answer.")]}
    client = RecordingResponsesClient(response)
    history = [
        {"role": "user", "content": "Who wrote Dune?"},
        {"role": "assistant", "content": "Frank Herbert."},
    ]

    result = await process_perplexity_message(
        _request(),
        client,
        PerplexityConfig(
            model="perplexity/sonar",
            system_message="Answer with sources.",
            output_tokens=200,
        ),
        history,
    )

    assert result is not None
    payload = client.responses.create.call_args.kwargs
    assert payload["model"] == "perplexity/sonar"
    assert payload["instructions"] == "Answer with sources."
    assert payload["input"] == [
        *history,
        {"role": "user", "content": "What is the latest news?"},
    ]
    assert payload["max_output_tokens"] == 200
    assert payload["tools"] == [{"type": "web_search"}]
    assert "messages" not in payload
    assert "max_tokens" not in payload
    assert "temperature" not in payload


def test_agent_client_targets_the_versioned_responses_alias():
    client = VersionedClient({"output": [_message_item("ok")]})

    resolved = versioned_perplexity_client(client)

    assert resolved is client
    assert client.versioned_base_url == "https://api.perplexity.ai/v1"


@pytest.mark.asyncio
async def test_search_results_map_citation_ids_to_urls():
    text = "The first report [1] and the second report [2] disagree."
    response = {
        "output": [
            _search_item(
                [
                    {"id": 2, "url": URL_TWO, "title": "Second"},
                    {"id": 1, "url": URL_ONE, "title": "First"},
                ]
            ),
            _message_item(text),
        ]
    }
    client = RecordingResponsesClient(response)

    result = await process_perplexity_message(
        _request(),
        client,
        PerplexityConfig(),
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert response_text == text
    assert embed_data is not None
    assert embed_data["citations"] == {"1": URL_ONE, "2": URL_TWO}


@pytest.mark.asyncio
async def test_message_only_response_parses_without_citations():
    response = {"output": [_message_item("No search was needed for this answer.")]}
    client = RecordingResponsesClient(response)

    result = await process_perplexity_message(
        _request(),
        client,
        PerplexityConfig(),
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert response_text == "No search was needed for this answer."
    assert embed_data is None


@pytest.mark.asyncio
async def test_response_without_message_text_raises_value_error():
    response = {
        "output": [
            _search_item([{"id": 1, "url": URL_ONE}]),
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "not output_text"}],
            },
        ]
    }

    with pytest.raises(ValueError, match="no message text"):
        _parse_agent_response(response)

    result = await process_perplexity_message(
        _request(),
        RecordingResponsesClient(response),
        PerplexityConfig(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_bad_model_400_is_a_validation_error_and_is_not_retried():
    error = _api_error(
        openai.BadRequestError,
        400,
        "invalid model: perplexity/typo",
    )
    client = RecordingResponsesClient({})
    client.responses.create = AsyncMock(side_effect=error)

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_perplexity_message(
            _request(),
            client,
            PerplexityConfig(),
        )

    assert result is None
    assert client.responses.create.await_count == 1
    details = classify_error(error)
    assert details.error_type == ErrorType.VALIDATION_ERROR
    assert "invalid model" in details.message


@pytest.mark.asyncio
async def test_rate_limit_429_is_classified_and_retried_once():
    error = _api_error(openai.RateLimitError, 429, "rate limit exceeded")
    client = RecordingResponsesClient({})
    client.responses.create = AsyncMock(side_effect=error)

    with patch("src.error_handling.asyncio.sleep", new=AsyncMock()):
        result = await process_perplexity_message(
            _request(),
            client,
            PerplexityConfig(),
        )

    assert result is None
    assert client.responses.create.await_count == 2
    details = classify_error(error)
    assert details.error_type == ErrorType.API_RATE_LIMIT


@pytest.mark.asyncio
async def test_default_model_is_current_and_healthy():
    assert DEFAULT_PERPLEXITY_MODEL == "perplexity/sonar"
    assert PerplexityConfig().model == DEFAULT_PERPLEXITY_MODEL

    client = VersionedModelsClient(DEFAULT_PERPLEXITY_MODEL)
    monitor = APIHealthMonitor()

    result = await monitor.check_perplexity_health(
        client,
        {"PERPLEXITY_MODEL": DEFAULT_PERPLEXITY_MODEL},
    )

    assert result.status == "healthy"
    assert result.details["model"] == DEFAULT_PERPLEXITY_MODEL
    assert client.versioned_base_url == "https://api.perplexity.ai/v1"


def test_legacy_sonar_model_only_warns_at_startup():
    issues = validate_perplexity_config(
        {
            "PERPLEXITY_API_KEY": "pplx-" + "a" * 32,
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "PERPLEXITY_MODEL": "sonar-pro",
        }
    )

    assert not any(issue.startswith("ERROR:") for issue in issues)
    assert any(
        issue.startswith("WARNING: Unknown Perplexity model") and "perplexity/sonar" in issue
        for issue in issues
    )
