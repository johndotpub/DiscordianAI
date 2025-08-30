"""Tests for Discord embed formatting functionality."""

import discord

from src.discord_embeds import CitationEmbedFormatter, citation_embed_formatter


class TestCitationEmbedFormatter:
    """Test the CitationEmbedFormatter class."""

    def test_create_citation_embed_basic(self):
        """Test basic citation embed creation."""
        formatter = CitationEmbedFormatter()

        content = "AI is advancing rapidly [1] and machine learning [2] shows promise."
        citations = {
            "1": "https://example.com/ai-advances",
            "2": "https://example.com/ml-progress",
        }

        embed = formatter.create_citation_embed(content, citations)

        # Verify embed properties
        assert isinstance(embed, discord.Embed)
        assert embed.color.value == 0x5865F2  # Discord blurple
        assert "[[1]](https://example.com/ai-advances)" in embed.description
        assert "[[2]](https://example.com/ml-progress)" in embed.description
        assert "📚 2 sources" in embed.footer.text

    def test_create_citation_embed_with_title(self):
        """Test citation embed creation with custom title."""
        formatter = CitationEmbedFormatter()

        content = "Research shows progress [1]."
        citations = {"1": "https://example.com/research"}
        title = "Research Update"

        embed = formatter.create_citation_embed(content, citations, title=title)

        assert embed.title == "Research Update"
        assert "[[1]](https://example.com/research)" in embed.description

    def test_create_citation_embed_no_citations(self):
        """Test embed creation with no citations."""
        formatter = CitationEmbedFormatter()

        content = "This is plain text with no citations."
        citations = {}

        embed = formatter.create_citation_embed(content, citations)

        assert embed.description == content
        assert embed.footer.text is None

    def test_create_citation_embed_custom_footer(self):
        """Test embed creation with custom footer."""
        formatter = CitationEmbedFormatter()

        content = "Content with citation [1]."
        citations = {"1": "https://example.com"}
        footer_text = "Custom footer text"

        embed = formatter.create_citation_embed(content, citations, footer_text=footer_text)

        assert embed.footer.text == footer_text

    def test_format_citations_for_embed_description(self):
        """Test citation formatting for embed description."""
        formatter = CitationEmbedFormatter()

        text = "AI research [1] and ML development [2] are advancing."
        citations = {"1": "https://ai-research.example", "2": "https://ml-dev.example"}

        formatted = formatter._format_citations_for_embed_description(text, citations)

        assert "[[1]](https://ai-research.example)" in formatted
        assert "[[2]](https://ml-dev.example)" in formatted
        assert "AI research" in formatted
        assert "ML development" in formatted

    def test_format_citations_missing_url(self):
        """Test citation formatting when URL is missing."""
        formatter = CitationEmbedFormatter()

        text = "Content with [1] and [2] citations."
        citations = {"1": "https://example.com"}  # Missing citation 2

        formatted = formatter._format_citations_for_embed_description(text, citations)

        assert "[[1]](https://example.com)" in formatted
        assert "[2]" in formatted  # Should remain unchanged
        assert "[[2]]" not in formatted

    def test_should_use_embed_for_response(self):
        """Test embed usage decision logic."""
        formatter = CitationEmbedFormatter()

        # Should use embed when citations present
        assert formatter.should_use_embed_for_response("content", {"1": "url"}) is True

        # Should not use embed when no citations
        assert formatter.should_use_embed_for_response("content", {}) is False
        assert formatter.should_use_embed_for_response("content", None) is False

        # Should use embed when forced
        assert formatter.should_use_embed_for_response("content", None, force_embed=True) is True

    def test_create_error_embed(self):
        """Test error embed creation."""
        formatter = CitationEmbedFormatter()

        error_message = "Something went wrong"
        embed = formatter.create_error_embed(error_message)

        assert isinstance(embed, discord.Embed)
        assert embed.title == "🔧 Error"
        assert embed.description == error_message
        assert embed.color.value == 0xED4245  # Discord red

    def test_embed_description_length_limit(self):
        """Test that embed descriptions are truncated if too long."""
        formatter = CitationEmbedFormatter()

        # Create content longer than 4096 characters
        long_content = "A" * 5000 + " [1]"
        citations = {"1": "https://example.com"}

        embed = formatter.create_citation_embed(long_content, citations)

        # Should be truncated to fit Discord's limit
        assert len(embed.description) <= 4096
        assert embed.description.endswith("...")

    def test_global_formatter_instance(self):
        """Test that global formatter instance is available."""
        assert isinstance(citation_embed_formatter, CitationEmbedFormatter)
        assert citation_embed_formatter.color == 0x5865F2

    def test_single_vs_plural_footer(self):
        """Test footer text for single vs multiple citations."""
        formatter = CitationEmbedFormatter()

        # Single citation
        embed_single = formatter.create_citation_embed("Content [1]", {"1": "https://example.com"})
        assert "1 source" in embed_single.footer.text

        # Multiple citations
        embed_multiple = formatter.create_citation_embed(
            "Content [1] and [2]", {"1": "https://example.com", "2": "https://test.com"}
        )
        assert "2 sources" in embed_multiple.footer.text
