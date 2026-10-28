"""Discord embed utilities for DiscordianAI bot.

This module provides utilities for creating Discord embeds with proper
citation formatting and hyperlink support.
"""

import logging

import discord

from .citation_formatting import format_citations
from .config import (
    EMBED_LIMIT,
    EMBED_SAFE_LIMIT,
)
from .truncation import truncate_with_notice


class CitationEmbedFormatter:
    """Formats Perplexity responses with citations into Discord embeds.

    Discord only supports clickable hyperlinks in embed descriptions and fields,
    not in regular message content. This class handles the conversion of
    citation-formatted text into proper Discord embeds.
    """

    def __init__(self, color: int = 0x5865F2):  # Discord blurple
        """Initialize the citation embed formatter.

        Args:
            color: Hex color for embed sidebar (default: Discord blurple)
        """
        self.color = color
        self.logger = logging.getLogger(__name__)

    def create_citation_embed(
        self,
        content: str,
        citations: dict[str, str],
        title: str | None = None,
        footer_text: str | None = None,
    ) -> tuple[discord.Embed, dict]:
        """Create a Discord embed with properly formatted citations.

        Args:
            content: Main response content with citation markers like [1], [2]
            citations: Dictionary mapping citation numbers to URLs
            title: Optional embed title
            footer_text: Optional footer text

        Returns:
            tuple[discord.Embed, dict]: (embed, metadata) where metadata contains truncation info
        """
        # Create the base embed
        embed = discord.Embed(color=self.color)

        if title:
            embed.title = title

        # Format the content with clickable citations for embed description
        formatted_content = self._format_citations_for_embed_description(content, citations)
        original_formatted_length = len(formatted_content)

        # Discord embed description has a character limit
        was_truncated = original_formatted_length > EMBED_LIMIT
        if was_truncated:
            formatted_content, _ = truncate_with_notice(formatted_content, EMBED_SAFE_LIMIT, "...")
            self.logger.warning(
                "Embed description truncated from %d to %d chars",
                original_formatted_length,
                EMBED_SAFE_LIMIT,
            )

        embed.description = formatted_content

        # Add footer if provided
        if footer_text:
            embed.set_footer(text=footer_text)
        elif citations:
            # Default footer showing citation count
            citation_count = len(citations)
            embed.set_footer(
                text=f"📚 {citation_count} source{'s' if citation_count != 1 else ''}",
            )

        # Create metadata about the embed
        metadata = {
            "was_truncated": was_truncated,
            "original_length": len(content),
            "formatted_length": original_formatted_length,
        }

        self.logger.debug("Created citation embed with %d citations", len(citations))
        return embed, metadata

    def _format_citations_for_embed_description(self, text: str, citations: dict[str, str]) -> str:
        """Format citation numbers as clickable hyperlinks for Discord embed description.

        Args:
            text: Text containing citation markers like [1], [2]
            citations: Dictionary mapping citation numbers to URLs

        Returns:
            str: Text with citations formatted as Discord hyperlinks
        """
        formatted_text = format_citations(text, citations, style="embed")

        self.logger.debug("Formatted %d citations for embed description", len(citations))
        return formatted_text


# Global instance for easy access
citation_embed_formatter = CitationEmbedFormatter()
