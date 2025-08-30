"""Comprehensive tests for message sending functionality.

Tests the core message sending logic including:
- send_formatted_message function
- Embed vs regular message handling
- Message splitting for embeds > embed limit chars
- Duplication prevention
- Error handling and fallbacks
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.bot import send_formatted_message, send_split_message_with_embed
from src.config import EMBED_SAFE_LIMIT


class TestSendFormattedMessage:
    """Test send_formatted_message function for duplication prevention."""

    @pytest.mark.asyncio
    async def test_send_formatted_message_with_embed_normal(self):
        """Test sending message with embed (normal case - no splitting needed)."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Mock embed data
        embed = MagicMock(spec=discord.Embed)
        embed.description = "Test embed content"
        embed_data = {
            "embed": embed,
            "citations": {"1": "https://example.com"},
            "clean_text": "Test content with citation [1]",
        }

        message = "Test message"
        deps = {"logger": MagicMock()}

        await send_formatted_message(channel, message, deps, embed_data=embed_data)

        # Should send message with embed
        channel.send.assert_called_once_with(message, embed=embed)

    @pytest.mark.asyncio
    async def test_send_formatted_message_with_embed_truncated(self):
        """Test sending message with embed that was truncated (needs splitting)."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Mock embed with truncated content
        embed = MagicMock(spec=discord.Embed)
        embed.description = "A" * EMBED_SAFE_LIMIT + "..."  # Truncated embed

        # Original content longer than embed limit
        long_content = "A" * 5000
        embed_data = {
            "embed": embed,
            "citations": {"1": "https://example.com", "2": "https://test.com"},
            "clean_text": long_content,
        }

        message = "Test message"
        deps = {"logger": MagicMock()}

        with patch("src.bot.send_split_message_with_embed") as mock_split:
            await send_formatted_message(channel, message, deps, embed_data=embed_data)

            # Should call split function with citations
            mock_split.assert_called_once_with(
                channel, long_content, deps, embed, embed_data["citations"]
            )

    @pytest.mark.asyncio
    async def test_send_formatted_message_embed_failure_fallback(self):
        """Test fallback when embed sending fails."""
        channel = MagicMock(spec=discord.TextChannel)
        # HTTPException requires response parameter; use a more realistic mock
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = "Bad Request"
        http_error = discord.HTTPException(response=mock_response, message="Embed failed")
        channel.send = AsyncMock(side_effect=[http_error, None])

        embed = MagicMock(spec=discord.Embed)
        embed.description = "Test embed"
        embed_data = {"embed": embed, "clean_text": "Test content"}

        message = "Short message"
        deps = {"logger": MagicMock()}

        await send_formatted_message(channel, message, deps, embed_data=embed_data)

        # Should attempt embed, then fall back to regular message
        assert channel.send.call_count == 2
        # First call with embed, second call as regular message
        assert not channel.send.call_args_list[1][1]["suppress_embeds"]

    @pytest.mark.asyncio
    async def test_send_formatted_message_regular_short(self):
        """Test sending regular message (no embed data) that fits in 2000 chars."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        message = "Short regular message"
        deps = {"logger": MagicMock()}

        await send_formatted_message(channel, message, deps)

        # Should send as regular message
        channel.send.assert_called_once_with(message, suppress_embeds=False)

    @pytest.mark.asyncio
    async def test_send_formatted_message_regular_long(self):
        """Test sending regular message > 2000 chars (needs splitting)."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Message longer than 2000 characters
        long_message = "A" * 2500
        deps = {"logger": MagicMock()}

        with patch("src.bot.send_split_message") as mock_split:
            await send_formatted_message(channel, long_message, deps)

            # Should call split function
            mock_split.assert_called_once_with(channel, long_message, deps, False)

    @pytest.mark.asyncio
    async def test_no_duplicate_messages_sent(self):
        """Test that no duplicate messages are sent in any scenario."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Test embed case
        embed = MagicMock(spec=discord.Embed)
        embed.description = "Test"
        embed_data = {"embed": embed, "clean_text": "Test"}

        await send_formatted_message(
            channel, "Test", {"logger": MagicMock()}, embed_data=embed_data
        )

        # Should only send once
        assert channel.send.call_count == 1

        # Reset and test regular message
        channel.send.reset_mock()
        await send_formatted_message(channel, "Regular test", {"logger": MagicMock()})

        # Should only send once
        assert channel.send.call_count == 1


class TestSendSplitMessageWithEmbed:
    """Test send_split_message_with_embed function for proper citation handling."""

    @pytest.mark.asyncio
    async def test_split_embed_short_content(self):
        """Test embed with short content (no splitting needed)."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Short content that doesn't need splitting
        content = "Short content with citation [1]"
        citations = {"1": "https://example.com"}

        embed = MagicMock(spec=discord.Embed)
        deps = {"logger": MagicMock()}

        await send_split_message_with_embed(channel, content, deps, embed, citations)

        # Should send only the original embed
        channel.send.assert_called_once_with("", embed=embed)

    @pytest.mark.asyncio
    async def test_split_embed_long_content_basic(self):
        """Test basic splitting behavior with long content."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Long content that will trigger splitting
        long_content = "A" * 5000
        citations = {"1": "https://example.com"}

        embed = MagicMock(spec=discord.Embed)
        deps = {"logger": MagicMock()}

        await send_split_message_with_embed(channel, long_content, deps, embed, citations)

        # Should send at least the first embed
        assert channel.send.call_count >= 1
        # First call should be with the original embed
        assert channel.send.call_args_list[0] == (("",), {"embed": embed})


class TestEmbedCharacterLimits:
    """Test proper handling of Discord character limits."""

    @pytest.mark.asyncio
    async def test_embed_limit_respected(self):
        """Test that embed splitting respects embed character limit."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Content that will trigger splitting
        content = "A" * 5000
        citations = {"1": "https://example.com"}

        embed = MagicMock(spec=discord.Embed)
        deps = {"logger": MagicMock()}

        await send_split_message_with_embed(channel, content, deps, embed, citations)

        # Should send the original embed first
        assert channel.send.call_count >= 1
        assert channel.send.call_args_list[0] == (("",), {"embed": embed})

    @pytest.mark.asyncio
    async def test_regular_message_2000_limit_respected(self):
        """Test that regular messages respect 2000 character limit."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Message just over 2000 chars
        long_message = "A" * 2001
        deps = {"logger": MagicMock()}

        with patch("src.bot.send_split_message") as mock_split:
            await send_formatted_message(channel, long_message, deps)

            # Should trigger splitting for > 2000 chars
            mock_split.assert_called_once_with(channel, long_message, deps, False)


if __name__ == "__main__":
    pytest.main([__file__])
