"""Tests for Perplexity API processing and citation handling."""

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import AIRequest, PerplexityConfig
from src.perplexity_processing import (
    extract_citations_from_response,
    format_citations_for_discord,
    process_perplexity_message,
)
from tests.test_utils import FakePerplexityClient


def test_extract_citations_from_response():
    # Test with modern Perplexity format (citations in metadata)
    text_with_citations = "AI is advancing rapidly [1] and GPT-5 shows promise [2]."
    api_citations = [
        "https://ai-research.example.com/advances",
        "https://gpt5.example.com/promise",
    ]

    clean_text, citations = extract_citations_from_response(text_with_citations, api_citations)

    assert "[1]" in text_with_citations
    assert clean_text.strip()
    assert isinstance(citations, dict)
    assert citations["1"] == "https://ai-research.example.com/advances"
    assert citations["2"] == "https://gpt5.example.com/promise"


def test_format_citations_for_discord():
    text = "AI is advancing [1] and machine learning [2] is improving."
    citations = {"1": "https://test-site.example", "2": "https://demo-site.example"}

    formatted = format_citations_for_discord(text, citations, linkify=True)
    assert "[1](https://test-site.example)" in formatted
    assert "[2](https://demo-site.example)" in formatted


def test_format_citations_plain_markers():
    text = "AI is advancing [1] and machine learning [2] is improving."
    citations = {"1": "https://test-site.example", "2": "https://demo-site.example"}

    formatted = format_citations_for_discord(text, citations, linkify=False)
    assert "[1]" in formatted and "[2]" in formatted
    assert "https://test-site.example" not in formatted
    assert "https://demo-site.example" not in formatted


@pytest.mark.asyncio
async def test_process_perplexity_message_success():
    mock_user = MagicMock()
    mock_user.id = 1

    from src.conversation_manager import ThreadSafeConversationManager

    manager = ThreadSafeConversationManager()
    logger = MagicMock()

    request = AIRequest(
        message="What's the weather today?",
        user=mock_user,
        conversation_manager=manager,
        logger=logger,
    )

    result = await process_perplexity_message(
        request,
        FakePerplexityClient(response_text="Test response from Perplexity [1]"),
        PerplexityConfig(),
    )

    assert result is not None
    res_text, _, embed = result
    assert "Test response from Perplexity" in res_text
    assert embed is None


@pytest.mark.asyncio
async def test_process_perplexity_message_failure():
    mock_user = MagicMock()
    mock_user.id = 2
    logger = MagicMock()

    class FailingClient:
        class Chat:
            class Completions:
                async def create(self, *_args, **_kwargs):
                    error_msg = "API failure!"
                    raise Exception(error_msg)

            completions = Completions()

        chat = Chat()

    request = AIRequest(
        message="Query",
        user=mock_user,
        conversation_manager=MagicMock(),
        logger=logger,
    )

    result = await process_perplexity_message(request, FailingClient(), PerplexityConfig())
    assert result is None


@pytest.mark.asyncio
async def test_process_perplexity_message_timeout():
    mock_user = MagicMock()
    mock_user.id = 999
    logger = MagicMock()

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=TimeoutError("Timeout"))

    request = AIRequest(
        message="Query",
        user=mock_user,
        conversation_manager=MagicMock(),
        logger=logger,
    )

    result = await process_perplexity_message(request, mock_client, PerplexityConfig())
    assert result is None
    logger.exception.assert_called()


@pytest.mark.asyncio
async def test_process_perplexity_message_empty_response():
    mock_user = MagicMock()
    logger = MagicMock()

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="   "))]),
    )

    request = AIRequest(
        message="Query",
        user=mock_user,
        conversation_manager=MagicMock(),
        logger=logger,
    )

    result = await process_perplexity_message(request, mock_client, PerplexityConfig())
    assert result is None
    logger.warning.assert_called_with("Perplexity returned empty response content")


@pytest.mark.asyncio
async def test_process_perplexity_message_with_citations():
    mock_user = MagicMock()
    mock_user.id = 3

    from src.conversation_manager import ThreadSafeConversationManager

    manager = ThreadSafeConversationManager()
    logger = MagicMock()

    request = AIRequest(
        message="AI?",
        user=mock_user,
        conversation_manager=manager,
        logger=logger,
    )

    client = FakePerplexityClient("AI is advancing [1].", ["https://example.com"])

    result = await process_perplexity_message(request, client, PerplexityConfig())
    assert result is not None
    res_text, _, embed_data = result
    assert "AI is advancing [1]" in res_text
    assert "https://example.com" not in res_text
    assert embed_data is not None
    assert "embed" in embed_data
    assert "[[1]](https://example.com)" in embed_data["embed"].description


@pytest.mark.asyncio
async def test_process_perplexity_message_with_urls():
    mock_user = MagicMock()
    mock_user.id = 4

    from src.conversation_manager import ThreadSafeConversationManager

    manager = ThreadSafeConversationManager()
    logger = MagicMock()

    request = AIRequest(
        message="Check https://example.com",
        user=mock_user,
        conversation_manager=manager,
        logger=logger,
    )

    client = FakePerplexityClient("Great [1]!", ["https://example.com"])

    result = await process_perplexity_message(request, client, PerplexityConfig())
    assert result is not None
    _, _, embed_data = result
    assert embed_data["citations"]["1"] == "https://example.com"


@pytest.mark.asyncio
async def test_process_perplexity_strips_citation_url_footers():
    """Ensure footnote-style citation URLs are removed from the message body."""
    mock_user = MagicMock()
    mock_user.id = 5

    from src.conversation_manager import ThreadSafeConversationManager

    manager = ThreadSafeConversationManager()
    logger = MagicMock()

    response_text = (
        "Headline update [1] and details [2].\n"
        "[1] https://example.com/source-one\n"
        "[2] https://example.com/source-two"
    )

    client = FakePerplexityClient(
        response_text,
        ["https://example.com/source-one", "https://example.com/source-two"],
    )

    request = AIRequest(
        message="Latest news?",
        user=mock_user,
        conversation_manager=manager,
        logger=logger,
    )

    result = await process_perplexity_message(request, client, PerplexityConfig())

    assert result is not None
    res_text, _, _ = result

    lines = [ln.strip() for ln in res_text.splitlines() if ln.strip()]
    assert all(not re.match(r"^\[?\d+\]?\s*https?://", ln) for ln in lines)
    assert "https://example.com/source-one" not in res_text
    assert "https://example.com/source-two" not in res_text
    assert "[1]" in res_text and "[2]" in res_text


def test_extract_citations_converts_markdown_links_to_markers():
    text = "Headline [1](https://example.com/a) and follow-up [2](https://example.com/b)."
    clean_text, citations = extract_citations_from_response(
        text,
        ["https://example.com/a", "https://example.com/b"],
    )

    assert "[1]" in clean_text and "[2]" in clean_text
    assert "(https://example.com/a)" not in clean_text
    assert "(https://example.com/b)" not in clean_text
