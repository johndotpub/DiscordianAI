"""Discord embed utilities for DiscordianAI bot.

This module provides utilities for creating Discord embeds with proper
citation formatting and hyperlink support.
"""

import logging

import discord

from .config import CITATION_PATTERN


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
    ) -> discord.Embed:
        """Create a Discord embed with properly formatted citations.

        Args:
            content: Main response content with citation markers like [1], [2]
            citations: Dictionary mapping citation numbers to URLs
            title: Optional embed title
            footer_text: Optional footer text

        Returns:
            discord.Embed: Formatted embed with clickable citation links
        """
        # Create the base embed
        embed = discord.Embed(color=self.color)

        if title:
            embed.title = title

        # Format the content with clickable citations for embed description
        formatted_content = self._format_citations_for_embed_description(content, citations)

        # Discord embed description has a 4096 character limit
        if len(formatted_content) > 4096:
            # Truncate and add notice
            formatted_content = formatted_content[:4090] + "..."
            self.logger.warning(
                f"Embed description truncated from {len(formatted_content)} to 4096 chars"
            )

        embed.description = formatted_content

        # Add footer if provided
        if footer_text:
            embed.set_footer(text=footer_text)
        elif citations:
            # Default footer showing citation count
            citation_count = len(citations)
            embed.set_footer(
                text=f"📚 {citation_count} source{'s' if citation_count != 1 else ''}"
            )

        self.logger.debug(f"Created citation embed with {len(citations)} citations")
        return embed

    def _format_citations_for_embed_description(self, text: str, citations: dict[str, str]) -> str:
        """Format citation numbers as clickable hyperlinks for Discord embed description.

        Args:
            text: Text containing citation markers like [1], [2]
            citations: Dictionary mapping citation numbers to URLs

        Returns:
            str: Text with citations formatted as Discord hyperlinks
        """
        if not citations:
            return text



        def replace_citation(match):
            citation_num = match.group(1)
            if citation_num in citations:
                url = citations[citation_num]
                # Format as clickable hyperlink for Discord embed
                return f"[[{citation_num}]]({url})"
            return match.group(0)  # Return original if no URL found

        # Replace [1], [2], etc. with clickable hyperlinks
        formatted_text = CITATION_PATTERN.sub(replace_citation, text)

        self.logger.debug(f"Formatted {len(citations)} citations for embed description")
        return formatted_text

    def should_use_embed_for_response(
        self,
        content: str,  # noqa: ARG002
        citations: dict[str, str] | None = None,
        force_embed: bool = False,
    ) -> bool:
        """Determine if a response should be formatted as an embed.

        Args:
            content: Response content
            citations: Optional citation dictionary
            force_embed: Force embed usage regardless of other factors

        Returns:
            bool: True if response should use embed formatting
        """
        if force_embed:
            return True

                # Use embed if citations are present (primary use case)
        return bool(citations and len(citations) > 0)

    def create_error_embed(self, error_message: str, title: str = "Error") -> discord.Embed:
        """Create an error embed for consistent error messaging.

        Args:
            error_message: Error description
            title: Error title

        Returns:
            discord.Embed: Formatted error embed
        """
        return discord.Embed(
            title=f"🔧 {title}", description=error_message, color=0xED4245  # Discord red
        )


# Global instance for easy access
citation_embed_formatter = CitationEmbedFormatter()
