"""Tests for Perplexity's native web_search and fetch_url tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import AIRequest, PerplexityConfig
from src.perplexity_processing import _build_api_params, process_perplexity_message

FETCHED_URL = "https://fetched.example/page"


class _ResponsesClient:
    def __init__(self, response):
        self.responses = SimpleNamespace(create=AsyncMock(return_value=response))


def _request(message="What does this page say? https://example.com/page"):
    return AIRequest(
        message=message,
        user=MagicMock(id=12345),
        conversation_manager=MagicMock(),
        logger=MagicMock(),
    )


def _message_item(text):
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def test_params_request_search_and_fetch_tools_with_bounded_steps():
    """The Agent API is asked for both tools and a bounded tool loop."""
    params = _build_api_params(
        "perplexity/sonar",
        "Answer with sources.",
        "Read https://example.com/page",
        500,
    )

    assert params["tools"] == [{"type": "web_search"}, {"type": "fetch_url"}]
    assert params["extra_body"]["max_steps"] == 3
    assert "max_steps" not in params
    assert params["instructions"].startswith("Answer with sources.")
    assert "fetch_url" in params["instructions"]
    assert "untrusted reference material" in params["instructions"]


@pytest.mark.asyncio
async def test_fetched_page_citations_map_like_search_results():
    """A citation marker points at a fetched page URL, not just search hits."""
    response = {
        "output": [
            {
                "type": "fetch_url_results",
                "contents": [{"id": 1, "url": FETCHED_URL, "title": "Fetched page"}],
            },
            _message_item("The page confirms the claim [1]."),
        ]
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert response_text == "The page confirms the claim [1]."
    assert embed_data is not None
    assert embed_data["citations"] == {"1": FETCHED_URL}
    assert f"[[1]]({FETCHED_URL})" in embed_data["embed"].description


@pytest.mark.asyncio
async def test_fetched_page_results_shape_without_ids_maps_by_position():
    """Older fetch output under ``results`` is accepted and mapped in order."""
    response = {
        "output": [
            {
                "type": "fetch_url_results",
                "results": [{"url": FETCHED_URL, "title": "Fetched page"}],
            },
            _message_item("The page confirms the claim [1]."),
        ]
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    assert result[2]["citations"] == {"1": FETCHED_URL}


@pytest.mark.asyncio
async def test_url_message_without_citations_has_no_scrape_note():
    """Per-URL fetch failures are the model's message, not a canned preamble."""
    response = {"output": [_message_item("I could not fetch that page.")]}

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    assert result[0] == "I could not fetch that page."
    assert "couldn't access" not in result[0]
    assert "**Note**" not in result[0]
