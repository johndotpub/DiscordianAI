from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.perplexity_processing import (
    extract_citations_from_response,
    format_citations_for_discord,
    process_perplexity_message,
    should_suppress_embeds,
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

    assert "[1]" in text_with_citations  # Original should have citations
    assert clean_text.strip()  # Should return cleaned text
    assert isinstance(citations, dict)  # Should return citation dict
    assert citations["1"] == "https://ai-research.example.com/advances"
    assert citations["2"] == "https://gpt5.example.com/promise"


def test_extract_citations_legacy_format():
    # Test with legacy format (URLs in text) for backward compatibility
    text_with_citations = (
        "AI is advancing rapidly [1] and GPT-5 shows promise [2]. "
        "Here's a URL: https://test-domain.example"
    )
    clean_text, citations = extract_citations_from_response(text_with_citations, None)

    assert clean_text.strip()  # Should return cleaned text
    assert isinstance(citations, dict)  # Should return citation dict


def test_format_citations_for_discord():
    text = "AI is advancing [1] and machine learning [2] is improving."
    citations = {"1": "https://test-site.example", "2": "https://demo-site.example"}

    formatted = format_citations_for_discord(text, citations)
    # Test citation formatting - citations should remain as numbers but be clickable
    assert "[1](https://test-site.example)" in formatted
    assert "[2](https://demo-site.example)" in formatted
    # Verify URLs are present in formatted output
    assert any(url in formatted for url in citations.values())


def test_format_citations_for_discord_no_citations():
    text = "AI is advancing and machine learning is improving."
    citations = {}

    formatted = format_citations_for_discord(text, citations)
    assert formatted == text  # Should return unchanged


def test_should_suppress_embeds_multiple_links():
    text_with_multiple_links = (
        "Check [example.com](https://example.com) and [test.com](https://test.com)"
    )
    assert should_suppress_embeds(text_with_multiple_links) is True


def test_should_suppress_embeds_single_link():
    text_with_single_link = "Check [example.com](https://example.com)"
    # Counts both the markdown link AND the URL inside, so it returns True
    # This is actually correct behavior for the current implementation
    assert should_suppress_embeds(text_with_single_link) is True


def test_should_suppress_embeds_no_links():
    text_no_links = "This is just plain text"
    assert should_suppress_embeds(text_no_links) is False


@pytest.mark.asyncio
async def test_process_perplexity_message_success():
    mock_user = MagicMock()
    mock_user.id = 1

    # Create a mock ThreadSafeConversationManager
    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    result = await process_perplexity_message(
        "What's the weather today?",
        mock_user,
        conversation_manager,
        logger,
        FakePerplexityClient(response_text="Test response from Perplexity [1]"),
        "You are a helpful assistant.",
        8000,
        "sonar-pro",
    )

    assert result is not None
    _response_text, _suppress_embeds, embed_data = result
    assert "Test response from Perplexity" in _response_text
    assert isinstance(_suppress_embeds, bool)
    # embed_data should be None since test response has no citations
    assert embed_data is None

    # Check conversation was updated via the manager
    history = conversation_manager.get_conversation(mock_user.id)
    assert len(history) >= 1
    assert history[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_process_perplexity_message_failure():
    mock_user = MagicMock()
    mock_user.id = 2

    # Create a mock ThreadSafeConversationManager
    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    # Create a client that will raise an exception
    class FailingPerplexityClient:
        def __init__(self):
            self.chat = self.Chat()

        class Chat:
            def __init__(self):
                self.completions = self.Completions()

            class Completions:
                @staticmethod
                async def create(*args, **kwargs):
                    raise Exception("API failure!")

    result = await process_perplexity_message(
        "What's the weather today?",
        mock_user,
        conversation_manager,
        logger,
        FailingPerplexityClient(),
        "You are a helpful assistant.",
        8000,
        "sonar-pro",
    )

    assert result is None


@pytest.mark.asyncio
async def test_process_perplexity_message_with_citations():
    """Test processing Perplexity message with citations creates embed data."""
    mock_user = MagicMock()
    mock_user.id = 3

    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    result = await process_perplexity_message(
        "What's the latest in AI?",
        mock_user,
        conversation_manager,
        logger,
        FakePerplexityClient(
            "AI is advancing rapidly [1] and shows promise [2].",
            ["https://example.com/ai-research", "https://test.com/ai-future"],
        ),
        "You are a helpful assistant.",
        8000,
        "sonar-pro",
    )

    assert result is not None
    _response_text, _suppress_embeds, embed_data = result

    # Should have embed data since citations are present
    assert embed_data is not None
    assert "embed" in embed_data
    assert "citations" in embed_data
    assert "clean_text" in embed_data

    # When embed_data exists, response_text should contain the actual content
    # for conversation history, while the embed displays the formatted content
    assert (
        _response_text == "AI is advancing rapidly [1] and shows promise [2]."
    ), f"Expected actual content in response_text, got: '{_response_text}'"

    # Embed should contain the citations
    embed = embed_data["embed"]
    assert embed.description is not None
    assert "AI is advancing rapidly" in embed.description  # Content is in embed
    assert "[[1]]" in embed.description  # Citation hyperlinks in embed


@pytest.mark.asyncio
async def test_process_perplexity_message_with_urls():
    """Test processing Perplexity message with URLs creates proper search queries."""
    mock_user = MagicMock()
    mock_user.id = 4

    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    result = await process_perplexity_message(
        "Check this PR: https://github.com/johndotpub/DiscordianAI/pull/197",
        mock_user,
        conversation_manager,
        logger,
        FakePerplexityClient(
            "This PR looks great [1]!", ["https://github.com/johndotpub/DiscordianAI/pull/197"]
        ),
        "You are a helpful assistant.",
        8000,
        "sonar-pro",
    )

    assert result is not None
    _response_text, _suppress_embeds, embed_data = result

    # Should have embed data since citations are present
    assert embed_data is not None
    assert "embed" in embed_data
    assert "citations" in embed_data
    assert "clean_text" in embed_data
    assert "1" in embed_data["citations"]
    assert embed_data["citations"]["1"] == "https://github.com/johndotpub/DiscordianAI/pull/197"


@pytest.mark.asyncio
async def test_process_perplexity_message_scraping_failure():
    """Test handling of URL scraping failure with graceful fallback."""
    mock_user = MagicMock()
    mock_user.id = 5

    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    # Mock scraping failure
    with patch(
        "src.perplexity_processing.scrape_url_content", new_callable=AsyncMock
    ) as mock_scrape:
        mock_scrape.return_value = None  # Simulate scraping failure

        result = await process_perplexity_message(
            "Check this link: https://broken-link.com",
            mock_user,
            conversation_manager,
            logger,
            FakePerplexityClient("I couldn't access that link directly, but basic info is...", []),
            "System prompt",
            1000,
            "sonar-pro",
        )

        assert result is not None
        _response_text, _, _ = result

        # Should contain the user-facing note about access failure
        assert (
            "**Note**: I couldn't access the URL https://broken-link.com directly"
            in _response_text
        )


@pytest.mark.asyncio
async def test_process_perplexity_message_multi_url_mixed_success():
    """Test handling multiple URLs where some fail and some succeed."""
    mock_user = MagicMock()
    mock_user.id = 6

    from src.conversation_manager import ThreadSafeConversationManager

    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    # Mock scraping: first URL succeeds, second fails
    async def mock_scrape_side_effect(url, *args, **kwargs):
        if "good.com" in url:
            return "Valid content from good site"
        return None

    with patch(
        "src.perplexity_processing.scrape_url_content", side_effect=mock_scrape_side_effect
    ):
        result = await process_perplexity_message(
            "Compare https://good.com and https://bad.com",
            mock_user,
            conversation_manager,
            logger,
            FakePerplexityClient("Here is the comparison...", []),
            "System prompt",
            1000,
            "sonar-pro",
        )

        assert result is not None
        _response_text, _, _ = result

        # With the fix, valid content is detected, so NO generic fallback note is added
        # (Current limitation: partial failures are silent if at least one succeeds)
        assert "**Note**: I couldn't access" not in _response_text


@pytest.mark.asyncio
async def test_process_perplexity_message_with_scraped_content_formatting():
    """Test that scraped content is correctly formatted into the system prompt context."""
    mock_user = MagicMock()
    mock_user.id = 7
    conversation_manager = MagicMock()
    logger = MagicMock()

    # Create a spy client to inspect messages sent to it
    spy_client = MagicMock()
    spy_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="Response"))], citations=[]
        )
    )

    with patch(
        "src.perplexity_processing.scrape_url_content", new_callable=AsyncMock
    ) as mock_scrape:
        mock_scrape.return_value = "Title: Test Page\nMain content: Important info about AI."

        await process_perplexity_message(
            "Summarize https://example.com",
            mock_user,
            conversation_manager,
            logger,
            spy_client,
            "Base system prompt",
            1000,
            "sonar-pro",
        )

        # Verify the call to the client included the scraped content in messages
        call_kwargs = spy_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]

        # Find the user message or system message containing the scraped content
        content_found = False
        for msg in messages:
            if (
                "Content from https://example.com" in msg["content"]
                and "Important info about AI" in msg["content"]
            ):
                content_found = True
                break

        assert (
            content_found
        ), "Scraped content was not properly injected into the API messages payload"


@pytest.mark.asyncio
async def test_extract_citations_from_search_results():
    """Test citation extraction from search_results metadata (fallback)."""
    response_text = "According to sources [1] and [2]..."
    # No direct citations field
    search_results = [
        {"url": "https://example.com/1", "snippet": "..."},
        {"url": "https://example.com/2", "snippet": "..."},
    ]

    _clean_text, citations = extract_citations_from_response(
        response_text, response_citations=None, search_results=search_results
    )

    assert citations["1"] == "https://example.com/1"
    assert citations["2"] == "https://example.com/2"


@pytest.mark.asyncio
async def test_extract_citations_legacy_fallback():
    """Test legacy citation extraction where URLs are in the text."""
    # Legacy format: text + list of URLs at bottom or inline
    # Pattern matching typically looks for [N] and URL
    response_text = "Source: https://legacy.com/source [1]"

    _clean_text, citations = extract_citations_from_response(
        response_text, response_citations=None, search_results=None
    )

    assert citations["1"] == "https://legacy.com/source"


@pytest.mark.asyncio
async def test_process_perplexity_message_timeout():
    """Test handling of Perplexity API timeout."""
    mock_user = MagicMock()
    mock_user.id = 999
    conversation_manager = MagicMock()
    logger = MagicMock()

    # Mock client raising TimeoutError
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=TimeoutError("Timeout"))

    result = await process_perplexity_message(
        "Query", mock_user, conversation_manager, logger, mock_client
    )

    assert result is None
    # Verify we logged the timeout exception
    logger.exception.assert_called()
    assert "timed out" in logger.exception.call_args[0][0]


@pytest.mark.asyncio
async def test_process_perplexity_message_empty_response():
    """Test handling of empty response from Perplexity."""
    mock_user = MagicMock()
    conversation_manager = MagicMock()
    logger = MagicMock()

    mock_client = MagicMock()
    # Content is whitespace to pass the first check but fail the strip() check
    mock_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="   "))])
    )

    result = await process_perplexity_message(
        "Query", mock_user, conversation_manager, logger, mock_client
    )

    assert result is None
    logger.warning.assert_called_with("Perplexity returned empty response content")
