"""
Comprehensive tests for message splitting functionality.

This module tests all aspects of message splitting including:
- Basic splitting functionality
- Multiple part splitting
- Recursion limit handling
- Truncation behavior
- Content preservation
- Edge cases and error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.config import EMBED_SAFE_LIMIT, MESSAGE_LIMIT
from src.discord_embeds import citation_embed_formatter
from src.message_splitter import (
    adjust_split_for_code_blocks,
    find_optimal_split_point,
    send_split_message,
    send_split_message_with_embed,
)
from tests.helpers import create_mock_channel, create_test_context


class TestMessageSplittingBasic:
    """Test basic message splitting functionality."""

    def test_find_split_index_with_newline(self):
        """Test finding split point with newline."""
        message = "Line 1\nLine 2\nLine 3"
        middle = len(message) // 2
        split_index = find_optimal_split_point(message, middle)

        # Should find a newline near the middle
        assert split_index > 0
        assert split_index < len(message)
        assert message[split_index - 1] == "\n"

    def test_find_split_index_no_newline(self):
        """Test finding split point without newline."""
        message = "This is a very long message without any newlines at all"
        middle = len(message) // 2
        split_index = find_optimal_split_point(message, middle)

        # Should find a word boundary near the middle
        assert split_index > 0
        assert split_index < len(message)
        assert message[split_index - 1] == " "

    def test_split_at_sentence_boundary(self):
        """Test splitting at sentence boundaries."""
        message = "First sentence. Second sentence. Third sentence."
        middle = len(message) // 2
        split_index = find_optimal_split_point(message, middle)

        # Should find a sentence boundary
        assert split_index > 0
        assert split_index < len(message)
        # The function looks for sentence endings followed by whitespace
        assert message[split_index - 1] in [".", "!", "?"] or message[split_index - 1] == " "

    def test_split_at_word_boundary(self):
        """Test splitting at word boundaries."""
        message = "word1 word2 word3 word4 word5"
        middle = len(message) // 2
        split_index = find_optimal_split_point(message, middle)

        # Should find a word boundary
        assert split_index > 0
        assert split_index < len(message)
        assert message[split_index - 1] == " "

    def test_split_fallback_to_target(self):
        """Test fallback to target when no boundaries found."""
        message = "no_boundaries_here_at_all"
        middle = len(message) // 2
        split_index = find_optimal_split_point(message, middle)

        # Should fall back to target
        assert split_index == middle

    def test_split_near_start(self):
        """Test splitting near the start of message."""
        message = "Short start\nLong middle part here\nEnd"
        target = 5  # Very close to start
        split_index = find_optimal_split_point(message, target)

        # Should find a reasonable split point
        assert split_index > 0
        assert split_index < len(message)

    def test_split_near_end(self):
        """Test splitting near the end of message."""
        message = "Start\nMiddle\nShort end"
        target = len(message) - 5  # Very close to end
        split_index = find_optimal_split_point(message, target)

        # Should find a reasonable split point
        assert split_index > 0
        assert split_index < len(message)


class TestCodeBlockSplitting:
    """Test message splitting with code blocks."""

    def test_split_outside_code_block(self):
        """Test splitting outside code blocks."""
        message = "Normal text\n```\ncode block\n```\nMore text"
        split_point = 20
        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split normally outside code block
        # The function detects that split_point is inside the code block and adjusts
        assert before == "Normal text\n"
        assert after == "```\ncode block\n```\nMore text"

        outside_before, outside_after = adjust_split_for_code_blocks(
            "Text before ```code``` text after", 5
        )
        assert outside_before == "Text "
        assert outside_after == "before ```code``` text after"

    def test_split_inside_code_block_near_start(self):
        """Test splitting inside code block near start."""
        message = "Text\n```\ncode line 1\ncode line 2\n```\nMore text"
        split_point = 25  # Inside the code block
        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split after the code block (closer to end since 25 is closer to end)
        assert before == "Text\n```\ncode line 1\ncode line 2\n```"
        assert after == "\nMore text"

        near_start_before, near_start_after = adjust_split_for_code_blocks(
            "Text ```very long code block here``` more text", 10
        )
        assert near_start_before == "Text "
        assert near_start_after.startswith("```")

    def test_split_inside_code_block_near_end(self):
        """Test splitting inside code block near end."""
        message = "Text\n```\ncode line 1\ncode line 2\n```\nMore text"
        split_point = 45  # Near end of code block
        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split after the code block (closer to end)
        assert before == "Text\n```\ncode line 1\ncode line 2\n```\nMore tex"
        assert after == "t"

        inside_before, inside_after = adjust_split_for_code_blocks(
            "Text ```code block``` more text", 16
        )
        assert inside_before.endswith("```")
        assert inside_after == " more text"

    def test_split_multiple_code_blocks(self):
        """Test splitting with multiple code blocks."""
        message = "Text\n```\ncode1\n```\nMiddle\n```\ncode2\n```\nEnd"
        split_point = 30  # In second code block
        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should handle multiple code blocks correctly
        assert "```" in before
        assert "```" in after

    def test_split_no_code_blocks(self):
        """Test splitting with no code blocks."""
        message = "Just regular text with no code blocks at all"
        split_point = 20
        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split normally
        assert before == message[:split_point]
        assert after == message[split_point:]


class TestMessageSplittingIntegration:
    """Test integrated message splitting functionality."""

    @pytest.mark.asyncio
    async def test_send_split_message_short(self):
        """Test sending short message that doesn't need splitting."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "Short message"
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called once
        channel.send.assert_called_once()
        sent_message = channel.send.call_args[0][0]
        assert sent_message == message

    @pytest.mark.asyncio
    async def test_send_split_message_long(self):
        """Test sending long message that needs splitting."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        # Create a message longer than Discord's limit
        message = "A" * 3000
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called multiple times
        assert channel.send.call_count >= 2

        # All parts should be under the limit
        for call in channel.send.call_args_list:
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_mention_prefix_allows_full_length_message(self):
        """Ensure mention prefixes are counted against the Discord limit."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        original_message = MagicMock(spec=discord.Message)
        original_message.reply = AsyncMock()
        original_message.author = MagicMock()

        prefix = "<@123456789012345678> "
        body = "x" * (MESSAGE_LIMIT - len(prefix))
        deps = create_test_context()

        await send_split_message(
            channel,
            body,
            deps,
            original_message=original_message,
            mention_prefix=prefix,
        )

        original_message.reply.assert_called_once()
        sent = original_message.reply.call_args[0][0]
        assert sent.startswith(prefix)
        assert len(sent) <= MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_mention_prefix_triggers_split_without_overflow(self):
        """Messages that fit only without the prefix should be split safely."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        original_message = MagicMock(spec=discord.Message)
        original_message.reply = AsyncMock()
        original_message.author = MagicMock()

        prefix = "<@123456789012345678> "
        body = "x" * (MESSAGE_LIMIT - len(prefix) + 5)
        deps = create_test_context()

        await send_split_message(
            channel,
            body,
            deps,
            original_message=original_message,
            mention_prefix=prefix,
        )

        replies = [call.args[0] for call in original_message.reply.call_args_list]
        assert len(replies) >= 2
        assert replies[0].startswith(prefix)
        assert all(len(content) <= MESSAGE_LIMIT for content in replies)

    @pytest.mark.asyncio
    async def test_send_split_message_ignores_legacy_depth_hint(self):
        """A legacy recursion-depth hint must not truncate a deliverable message."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "x" * 5000
        deps = create_test_context()

        await send_split_message(channel, message, deps, _recursion_depth=15)

        sent_messages = [c[0][0] for c in channel.send.call_args_list]
        assert "".join(sent_messages) == message
        assert all(len(part) <= MESSAGE_LIMIT for part in sent_messages)
        assert not any("truncated" in part.lower() for part in sent_messages)

    @pytest.mark.asyncio
    async def test_send_split_message_discord_error(self):
        """Test handling of Discord API errors."""
        channel = create_mock_channel()
        channel.send = AsyncMock(side_effect=Exception("Discord API error"))

        message = "Test message"
        deps = create_test_context()

        # Should raise the exception
        with pytest.raises(Exception, match="Discord API error"):
            await send_split_message(channel, message, deps)

    @pytest.mark.asyncio
    async def test_multiple_parts_splitting(self):
        """Test that very long messages are split into multiple parts correctly."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        # Create a very long message (10,000 characters) to force multiple splits
        long_message = (
            "This is a very long message that needs to be split into multiple parts. " * 200
        )

        deps = create_test_context()

        await send_split_message(channel, long_message, deps)

        # Verify that channel.send was called multiple times
        call_count = channel.send.call_count
        assert call_count > 2, f"Expected multiple parts, got only {call_count}"

        # Collect all sent messages
        sent_messages = [call[0][0] for call in channel.send.call_args_list]

        # Verify each part is under the limit
        for i, part in enumerate(sent_messages):
            assert (
                len(part) <= MESSAGE_LIMIT
            ), f"Part {i + 1} ({len(part)}) exceeds Discord limit ({MESSAGE_LIMIT})"

        # Verify all content is preserved
        reconstructed_message = "".join(sent_messages)
        assert reconstructed_message == long_message, "Content was lost during splitting!"

    @pytest.mark.asyncio
    async def test_send_split_message_with_embed_respects_adjusted_split(self):
        """Ensure embed head and continuation align after code block adjustment."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        code_block = "```python\nprint('hello')\nprint('world')\n```\n"
        prefix = "Intro text before code block.\n"
        tail = "Trailing context after code block with citation [1]."
        padding = "x" * (EMBED_SAFE_LIMIT + 50)
        message = prefix + padding + code_block + tail

        # Build initial embed; it will be replaced for the head chunk when split occurs
        base_embed, _ = citation_embed_formatter.create_citation_embed(message, {})
        deps = create_test_context()

        mock_cont_embed = MagicMock(spec=discord.Embed)

        def _fake_embed(desc: str, *_args, **_kwargs):
            mock_cont_embed.description = desc
            return mock_cont_embed, None

        with patch(
            "src.message_splitter.citation_embed_formatter.create_citation_embed",
            side_effect=_fake_embed,
        ) as mock_create:
            await send_split_message_with_embed(
                channel,
                message,
                deps,
                base_embed,
                {"1": "https://example.com"},
                original_message=None,
                mention_prefix=None,
            )

            # First send uses rebuilt head embed aligned to the adjusted head chunk
            split_index = find_optimal_split_point(message, EMBED_SAFE_LIMIT)
            expected_head, expected_tail = adjust_split_for_code_blocks(message, split_index)

            first_call = channel.send.call_args_list[0]
            head_embed = first_call.kwargs.get("embed")
            assert head_embed is not None
            assert head_embed.description == expected_head

        # Continuation embed should be built from the adjusted tail text
        mock_create.assert_called()
        last_call = channel.send.call_args_list[-1]
        assert last_call.kwargs.get("embed") is mock_cont_embed
        assert mock_cont_embed.description == expected_tail.strip()

    @pytest.mark.asyncio
    async def test_content_preservation_no_truncation(self):
        """Test that content is preserved without truncation during normal splitting."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        # Create a very long message with natural break points
        long_message = """
This is a comprehensive explanation of Off the Grid controller settings from Gunzilla Games.

## Basic Controller Configuration

The controller settings in Off the Grid are designed to provide players with maximum
customization options while maintaining competitive balance. The game features several
key areas of controller configuration:

### Movement Settings
- **Sensitivity**: Adjustable from 0.1 to 10.0 with 0.1 increments
- **Deadzone**: Configurable from 0% to 50% to prevent stick drift
- **Acceleration**: Linear, exponential, and custom curves available
- **Invert Y-Axis**: Toggle for vertical look inversion

### Combat Settings
- **Aim Assist**: Multiple strength levels (Off, Low, Medium, High, Maximum)
- **Target Lock**: Optional feature for automatic target acquisition
- **Recoil Compensation**: Smart recoil control with adjustable intensity
- **Trigger Sensitivity**: Separate settings for left and right triggers

### Advanced Features
- **Adaptive Triggers**: Haptic feedback integration for PlayStation controllers
- **Gyro Controls**: Motion-based aiming for supported controllers
- **Button Mapping**: Complete customization of all controller inputs
- **Profile System**: Save and load multiple controller configurations

## Recent Updates

The latest patch (v2.1.3) introduced several new controller features:

1. **Smart Aiming**: AI-assisted targeting that learns from your playstyle
2. **Dynamic Sensitivity**: Automatically adjusts based on engagement distance
3. **Enhanced Haptics**: More detailed feedback for different weapon types
4. **Cross-Platform Profiles**: Controller settings sync across all platforms

## Competitive Considerations

For competitive play, the recommended settings are:
- Sensitivity: 3.5-4.5 for most players
- Deadzone: 5-10% to minimize input lag
- Aim Assist: Medium for balanced gameplay
- Recoil Compensation: 70-80% for optimal control

These settings provide the best balance between precision and responsiveness for most players.

## Troubleshooting

Common issues and solutions:
- **Stick Drift**: Increase deadzone by 2-3%
- **Over-aiming**: Reduce sensitivity by 0.5-1.0
- **Under-aiming**: Increase sensitivity gradually
- **Button Response**: Check trigger sensitivity settings

The controller system in Off the Grid is one of the most advanced in the industry,
offering players unprecedented control over their gaming experience.
""" * 3  # Make it even longer

        deps = create_test_context()

        await send_split_message(channel, long_message, deps)

        # Verify that channel.send was called
        assert channel.send.called, "channel.send should have been called"

        # Collect all sent messages
        sent_messages = [call[0][0] for call in channel.send.call_args_list]

        # Verify no part exceeds the limit
        for i, part in enumerate(sent_messages):
            assert (
                len(part) <= MESSAGE_LIMIT
            ), f"Part {i + 1} ({len(part)}) exceeds Discord limit ({MESSAGE_LIMIT})"

        # Verify all content is preserved (no truncation)
        reconstructed_message = "".join(sent_messages)
        assert reconstructed_message == long_message, "Content was lost during splitting!"

        # Verify no truncation messages
        for part in sent_messages:
            assert "truncated" not in part.lower(), f"Found truncation message: {part[:100]}..."
            assert "continues" not in part.lower(), f"Found continuation message: {part[:100]}..."

    @pytest.mark.asyncio
    async def test_25000_characters_are_delivered_without_truncation(self):
        """A 25,000-character answer is long, not a runaway, and arrives complete."""
        channel = create_mock_channel()

        # Make the mock raise an exception for messages over the limit
        async def mock_send(content, **kwargs):
            if len(content) > MESSAGE_LIMIT:
                from discord import HTTPException

                # Create a proper mock response object
                mock_response = MagicMock()
                mock_response.status = 400
                raise HTTPException(mock_response, "Message too long")
            return MagicMock()

        channel.send.side_effect = mock_send

        deps = create_test_context()

        message = "A" * 25000

        await send_split_message(channel, message, deps)

        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        assert all(len(part) <= MESSAGE_LIMIT for part in sent_messages)
        assert "".join(sent_messages) == message
        assert not any("truncated" in part.lower() for part in sent_messages)

    @pytest.mark.asyncio
    async def test_extreme_length_handling(self):
        """Test handling of extremely long messages."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        # Create an extremely long message (50,000 characters)
        extreme_message = "A" * 50000

        deps = create_test_context()

        await send_split_message(channel, extreme_message, deps)

        sent_messages = [call[0][0] for call in channel.send.call_args_list]

        # Every piece stays within Discord's limit and no content is lost.
        assert all(len(part) <= MESSAGE_LIMIT for part in sent_messages)
        assert "".join(sent_messages) == extreme_message
        assert not any("truncated" in part.lower() for part in sent_messages)

    @pytest.mark.asyncio
    async def test_simple_long_message(self):
        """Test splitting with a simple long message (no natural break points)."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        # Create a simple long message (no natural break points)
        message = "A" * 5000  # 5000 A's

        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Verify that channel.send was called multiple times
        call_count = channel.send.call_count
        expected_parts = (len(message) + MESSAGE_LIMIT - 1) // MESSAGE_LIMIT  # Ceiling division
        assert (
            call_count >= expected_parts - 1
        ), f"Too few parts: {call_count} < {expected_parts - 1}"
        assert (
            call_count <= expected_parts + 2
        ), f"Too many parts: {call_count} > {expected_parts + 2}"

        # Verify all parts are under limit
        for i, call in enumerate(channel.send.call_args_list):
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT, f"Part {i + 1} exceeds limit: {len(part)}"

        # Verify content preservation
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        reconstructed = "".join(sent_messages)
        assert reconstructed == message, "Content was lost during splitting!"


class TestMessageSplittingEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_empty_message(self):
        """Test handling of empty message."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = ""
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called once with empty message
        channel.send.assert_called_once()
        sent_message = channel.send.call_args[0][0]
        assert sent_message == ""
        assert find_optimal_split_point("", 0) == 0

    @pytest.mark.asyncio
    async def test_exactly_limit_length(self):
        """Test message that is exactly at the limit."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "A" * MESSAGE_LIMIT
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called once
        channel.send.assert_called_once()
        sent_message = channel.send.call_args[0][0]
        assert sent_message == message
        assert len(sent_message) == MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_one_over_limit(self):
        """Test message that is one character over the limit."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "A" * (MESSAGE_LIMIT + 1)
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called twice (split)
        assert channel.send.call_count == 2

        # Both parts should be under the limit
        for call in channel.send.call_args_list:
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_message_with_only_newlines(self):
        """Test message with only newlines."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "\n" * 3000
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called multiple times
        assert channel.send.call_count > 1

        # All parts should be under the limit
        for call in channel.send.call_args_list:
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_message_with_unicode_characters(self):
        """Test message with unicode characters."""
        channel = create_mock_channel()
        channel.send = AsyncMock()

        message = "🚀" * 3000  # Unicode emoji repeated - make it long enough to split
        deps = create_test_context()

        await send_split_message(channel, message, deps)

        # Should be called multiple times (unicode chars are longer than 1 byte)
        assert channel.send.call_count > 1

        # All parts should be under the limit
        for call in channel.send.call_args_list:
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT

        # Content should be preserved
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        reconstructed = "".join(sent_messages)
        assert reconstructed == message

    def test_split_message_with_unicode_characters(self):
        """Test splitting messages with unicode characters."""
        unicode_message = "测试消息 日本語 한국어 العربية русский"
        long_unicode_message = unicode_message * 200  # Make it very long

        split_point = find_optimal_split_point(long_unicode_message, MESSAGE_LIMIT)
        assert split_point > 0
        assert split_point < len(long_unicode_message)

        part1, part2 = adjust_split_for_code_blocks(long_unicode_message, split_point)
        assert len(part1) <= MESSAGE_LIMIT
        # Unicode characters should be preserved
        assert "测试" in part1 or "测试" in part2

    def test_split_message_with_mixed_content(self):
        """Test splitting messages with text, emoji, and unicode."""
        mixed_message = (
            "Hello! 👋 This is a test message with emoji 😊 and unicode 测试消息 "
            "and regular text all mixed together 🎉"
        )
        long_mixed_message = mixed_message * 150

        split_point = find_optimal_split_point(long_mixed_message, MESSAGE_LIMIT)
        part1, part2 = adjust_split_for_code_blocks(long_mixed_message, split_point)

        assert len(part1) <= MESSAGE_LIMIT
        # Should preserve all content types
        assert len(part1) + len(part2) == len(long_mixed_message)

    def test_split_message_with_emoji_in_code_blocks(self):
        """Test splitting messages with emoji inside code blocks."""
        code_with_emoji = """Here's some code:
```python
print("Hello 👋")
print("Test 🎉")
```
More text here."""

        long_code = code_with_emoji * 50
        split_point = find_optimal_split_point(long_code, MESSAGE_LIMIT)
        part1, part2 = adjust_split_for_code_blocks(long_code, split_point)

        # Code blocks should not be broken
        assert "```" in part1 or "```" in part2
        # Emoji in code should be preserved
        assert "👋" in part1 or "👋" in part2

    def test_split_message_with_unicode_in_code_blocks(self):
        """Test splitting messages with unicode inside code blocks."""
        code_with_unicode = """Code example:
```python
message = "测试消息"
print(message)
```
End of code."""

        long_code = code_with_unicode * 50
        split_point = find_optimal_split_point(long_code, MESSAGE_LIMIT)
        part1, part2 = adjust_split_for_code_blocks(long_code, split_point)

        # Unicode in code should be preserved
        assert "测试" in part1 or "测试" in part2

    def test_split_message_with_emoji_sequences(self):
        """Test splitting with emoji sequences (multiple emoji together)."""
        emoji_sequence = "👨‍👩‍👧‍👦 🎉🎊🎈 🚀🌟✨"
        long_sequence = emoji_sequence * 200

        split_point = find_optimal_split_point(long_sequence, MESSAGE_LIMIT)
        part1, part2 = adjust_split_for_code_blocks(long_sequence, split_point)

        # Emoji sequences should be preserved
        assert len(part1) + len(part2) == len(long_sequence)

    def test_split_message_with_mixed_emoji_and_unicode(self):
        """Test splitting with both emoji and unicode in same message."""
        mixed = "Hello 👋 测试 😊 日本語 🎉 한국어"
        long_mixed = mixed * 150

        split_point = find_optimal_split_point(long_mixed, MESSAGE_LIMIT)
        part1, part2 = adjust_split_for_code_blocks(long_mixed, split_point)

        # Both should be preserved
        assert "👋" in part1 or "👋" in part2
        assert "测试" in part1 or "测试" in part2
        assert len(part1) + len(part2) == len(long_mixed)
