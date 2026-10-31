"""Malformed Agent API response coverage for Perplexity processing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import AIRequest, PerplexityConfig
from src.perplexity_processing import (
    extract_citations_from_response,
    process_perplexity_message,
)

URL_ONE = "https://search.example/one"
URL_TWO = "https://search.example/two"


class _ResponsesClient:
    """Fake SDK client exposing only the Agent API Responses resource."""

    def __init__(self, response: dict) -> None:
        self.responses = SimpleNamespace(create=AsyncMock(return_value=response))


def _message_item(text: str) -> dict:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def _search_item(results) -> dict:
    return {"type": "search_results", "results": results}


def _request(message: str = "What changed today?") -> AIRequest:
    return AIRequest(
        message=message,
        user=MagicMock(id=12345),
        conversation_manager=MagicMock(),
        logger=MagicMock(),
    )


@pytest.mark.asyncio
async def test_missing_output_returns_none_instead_of_inventing_an_answer():
    """A response with a null output item is treated as empty."""
    request = _request()

    result = await process_perplexity_message(
        request,
        _ResponsesClient({"output": None}),
        PerplexityConfig(),
    )

    assert result is None
    request.logger.warning.assert_called_once_with("Perplexity returned empty response content")


@pytest.mark.asyncio
async def test_single_mapping_output_item_is_parsed():
    """A provider that returns one output object instead of a list still answers."""
    response = {
        "output": {
            "type": "message",
            "content": [{"type": "output_text", "text": "Single item answer."}],
        }
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert response_text == "Single item answer."
    assert embed_data is None


@pytest.mark.asyncio
async def test_string_message_content_is_parsed():
    """A message whose content is a plain string is accepted as answer text."""
    response = {"output": [{"type": "message", "content": "Plain string answer."}]}

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    assert result[0] == "Plain string answer."


@pytest.mark.asyncio
async def test_empty_text_part_falls_through_to_the_next_part():
    """An empty text part is skipped without discarding the following text."""
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": ""},
                    {"type": "output_text", "text": "Second part."},
                ],
            }
        ]
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    assert result[0] == "Second part."


@pytest.mark.asyncio
async def test_single_search_result_mapping_is_mapped_by_id():
    """A search_results item holding one result object is mapped by its id."""
    response = {
        "output": [
            _search_item({"id": 1, "url": URL_ONE}),
            _message_item("See the report [1]."),
        ]
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    assert result[2] is not None
    assert result[2]["citations"] == {"1": URL_ONE}


@pytest.mark.asyncio
async def test_empty_search_results_do_not_fabricate_a_citation():
    """An empty search_results item leaves the marker unresolved."""
    response = {
        "output": [
            _search_item([]),
            _message_item("See the report [1]."),
        ]
    }

    result = await process_perplexity_message(
        _request(),
        _ResponsesClient(response),
        PerplexityConfig(),
    )

    assert result is not None
    response_text, _suppress_embeds, embed_data = result
    assert embed_data is None
    assert "[1]" in response_text


def test_out_of_range_metadata_index_does_not_map_a_url():
    """A citation number beyond the metadata list resolves to nothing."""
    cleaned_text, citations = extract_citations_from_response(
        "See the second report [2].",
        ["https://only.example/source"],
    )

    assert citations == {}
    assert "[2]" in cleaned_text


def test_search_result_without_a_url_is_skipped():
    """A result without a URL cannot shadow one that has a URL."""
    _cleaned_text, citations = extract_citations_from_response(
        "See the second report [2].",
        search_results=[{"id": 1}, {"id": 2, "url": URL_TWO}],
    )

    assert citations == {"2": URL_TWO}


def test_non_numeric_result_id_is_not_used_as_a_position():
    """A malformed id is ignored rather than treated as list order."""
    _cleaned_text, citations = extract_citations_from_response(
        "See the report [1].",
        search_results=[{"id": "not-a-number", "url": URL_ONE}],
    )

    assert citations == {}


def test_explicit_result_ids_do_not_fall_back_to_list_order():
    """When ids exist, marker 1 is not mapped to the first result by accident."""
    _cleaned_text, citations = extract_citations_from_response(
        "See the report [1].",
        search_results=[{"id": 2, "url": URL_TWO}],
    )

    assert citations == {}


def test_positional_result_out_of_range_does_not_map_a_url():
    """Legacy results without ids only map markers that have a list position."""
    _cleaned_text, citations = extract_citations_from_response(
        "See the third report [3].",
        search_results=[{"url": URL_ONE}],
    )

    assert citations == {}


def test_text_fallback_keeps_the_first_url_for_a_repeated_marker():
    """A later citation line cannot overwrite an earlier resolved URL."""
    text = (
        "First report [1] https://first.example/source\n"
        "Plain continuation\n"
        "Again [1] https://second.example/source"
    )

    _cleaned_text, citations = extract_citations_from_response(text)

    assert citations == {"1": "https://first.example/source"}
