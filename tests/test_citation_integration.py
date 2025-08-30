"""End-to-end integration tests for citation functionality.

This test suite validates the complete citation pipeline from Perplexity API
response to Discord embed rendering with clickable hyperlinks.
"""

from unittest.mock import MagicMock

import discord
import pytest

from src.config import EMBED_LIMIT
from src.conversation_manager import ThreadSafeConversationManager
from src.discord_embeds import CitationEmbedFormatter
from src.perplexity_processing import process_perplexity_message


class TestCitationIntegration:
    """Test the complete citation processing pipeline."""

    @pytest.mark.asyncio
    async def test_end_to_end_citation_processing(self):
        """Test complete citation flow from Perplexity response to Discord embed."""
        # Setup
        user = MagicMock()
        user.id = 12345
        conversation_manager = ThreadSafeConversationManager()
        logger = MagicMock()

        # Mock Perplexity response with citations and URLs
        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content, citations=None):
                self.choices = [FakeChoice(content)]
                # Add citations metadata (new Perplexity API format)
                self.citations = citations or [
                    "https://ai-research.example.com/breakthrough",
                    "https://ml-models.example.com/architectures",
                ]

        class FakePerplexityClient:
            class Chat:
                class Completions:
                    @staticmethod
                    def create(*args, **kwargs):
                        return FakeResponse(
                            "The latest AI developments include breakthrough research [1] "
                            "and new model architectures [2]. Recent studies show progress."
                        )

                completions = Completions()

            chat = Chat()

        # Process the message
        result = await process_perplexity_message(
            "What are the latest AI developments?",
            user,
            conversation_manager,
            logger,
            FakePerplexityClient(),
            "You are a helpful assistant with web search.",
            8000,
            "sonar-pro",
        )

        # Validate results
        assert result is not None
        response_text, suppress_embeds, embed_data = result

        # Should have embed data with citations
        assert embed_data is not None
        assert "embed" in embed_data
        assert "citations" in embed_data
        assert "clean_text" in embed_data

        # CRITICAL: When embed_data exists, response_text should be empty to prevent duplication
        assert response_text == "", f"Expected empty response_text to prevent duplication, got: '{response_text}'"
        
        # The embed should contain the actual content
        embed = embed_data["embed"]
        assert "The latest AI developments" in embed.description
        assert "[[1]](https://ai-research.example.com/breakthrough)" in embed.description
        assert "[[2]](https://ml-models.example.com/architectures)" in embed.description

        # Verify embed formatting
        assert isinstance(embed, discord.Embed)
        assert embed.description is not None

        # Check that citations are properly formatted as hyperlinks
        assert "[[1]](https://ai-research.example.com/breakthrough)" in embed.description
        assert "[[2]](https://ml-models.example.com/architectures)" in embed.description

        # Verify footer (should be the custom Perplexity footer)
        assert "🌐 Web search results" in embed.footer.text

        # CRITICAL: When embed_data exists, response_text should be empty to prevent duplication
        assert response_text == "", f"Expected empty response_text to prevent duplication, got: '{response_text}'"
        
        # The embed should contain the actual content
        embed = embed_data["embed"]
        assert "The latest AI developments" in embed.description

    def test_citation_embed_formatter_integration(self):
        """Test CitationEmbedFormatter integration with real citation data."""
        formatter = CitationEmbedFormatter()

        content = "Machine learning advances [1] and neural networks [2] show promise [3]."
        citations = {
            "1": "https://ml-advances.example.com",
            "2": "https://neural-nets.example.com",
            "3": "https://ai-promise.example.com",
        }

        # Test embed creation
        embed, metadata = formatter.create_citation_embed(content, citations)

        # Verify all citations are clickable
        for num, url in citations.items():
            expected_link = f"[[{num}]]({url})"
            assert expected_link in embed.description

        # Verify footer shows correct count
        assert "📚 3 sources" in embed.footer.text
        
        # Verify metadata
        assert isinstance(metadata, dict)
        assert metadata["was_truncated"] is False

    @pytest.mark.asyncio
    async def test_mixed_content_without_citations(self):
        """Test that responses without citations don't create embeds."""
        user = MagicMock()
        user.id = 54321
        conversation_manager = ThreadSafeConversationManager()
        logger = MagicMock()

        class FakePerplexityClient:
            class Chat:
                class Completions:
                    @staticmethod
                    def create(*args, **kwargs):
                        # Response without citations
                        return MagicMock(
                            choices=[
                                MagicMock(
                                    message=MagicMock(
                                        content="This is a simple response without citations."
                                    )
                                )
                            ]
                        )

                completions = Completions()

            chat = Chat()

        result = await process_perplexity_message(
            "Tell me about AI",
            user,
            conversation_manager,
            logger,
            FakePerplexityClient(),
        )

        assert result is not None
        response_text, suppress_embeds, embed_data = result

        # Should not have embed data since no citations
        assert embed_data is None
        assert "This is a simple response" in response_text

    def test_citation_edge_cases(self):
        """Test citation handling edge cases."""
        formatter = CitationEmbedFormatter()

        # Test with missing citation URLs
        content = "Research shows [1] and studies indicate [2] and data suggests [3]."
        citations = {"1": "https://research.example.com"}  # Missing 2 and 3

        embed, metadata = formatter.create_citation_embed(content, citations)

        # Should format available citation
        assert "[[1]](https://research.example.com)" in embed.description

        # Should leave missing citations unchanged
        assert "[2]" in embed.description
        assert "[3]" in embed.description
        assert "[[2]]" not in embed.description
        assert "[[3]]" not in embed.description
        
        # Verify metadata
        assert isinstance(metadata, dict)
        assert metadata["was_truncated"] is False

    def test_embed_character_limits(self):
        """Test embed handling of Discord character limits."""
        formatter = CitationEmbedFormatter()

        # Create content that exceeds embed description limit
        long_content = "A" * 5000 + " with citation [1]"
        citations = {"1": "https://example.com"}

        embed, metadata = formatter.create_citation_embed(long_content, citations)

        # Should be truncated to fit Discord limits
        assert len(embed.description) <= EMBED_LIMIT
        assert embed.description.endswith("...")
        
        # Verify metadata shows truncation
        assert metadata["was_truncated"] is True

    def test_no_citations_no_embed_decision(self):
        """Test that responses without citations don't trigger embed creation."""
        formatter = CitationEmbedFormatter()

        citations = {}

        should_use_embed = formatter.should_use_embed_for_response(citations)
        assert should_use_embed is False

        # Test with None citations
        should_use_embed = formatter.should_use_embed_for_response(None)
        assert should_use_embed is False
