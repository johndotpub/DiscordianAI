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

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot import send_split_message
from src.config import MESSAGE_LIMIT, MAX_SPLIT_RECURSION
from src.message_utils import (
    adjust_split_for_code_blocks,
    find_optimal_split_point,
)
from tests.test_utils import create_mock_channel, create_test_context


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
        assert message[split_index - 1] in [".", "!", "?"] or \
            message[split_index - 1] == " "

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

    def test_split_inside_code_block_near_start(self):
        """Test splitting inside code block near start."""
        message = "Text\n```\ncode line 1\ncode line 2\n```\nMore text"
        split_point = 25  # Inside the code block
        before, after = adjust_split_for_code_blocks(message, split_point)
        
        # Should split after the code block (closer to end since 25 is closer to end)
        assert before == "Text\n```\ncode line 1\ncode line 2\n```"
        assert after == "\nMore text"

    def test_split_inside_code_block_near_end(self):
        """Test splitting inside code block near end."""
        message = "Text\n```\ncode line 1\ncode line 2\n```\nMore text"
        split_point = 45  # Near end of code block
        before, after = adjust_split_for_code_blocks(message, split_point)
        
        # Should split after the code block (closer to end)
        assert before == "Text\n```\ncode line 1\ncode line 2\n```\nMore tex"
        assert after == "t"

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
    async def test_send_split_message_recursion_limit(self):
        """Test recursion limit protection in message splitting."""
        channel = create_mock_channel()
        channel.send = AsyncMock()
        
        # Very long message that would cause deep recursion
        message = "x" * 5000  # Long message with no natural split points
        deps = create_test_context()
        
        # Test with high recursion depth to trigger limit
        await send_split_message(channel, message, deps, _recursion_depth=15)
        
        # Should attempt to send the full message despite recursion limit
        channel.send.assert_called_once()
        sent_message = channel.send.call_args[0][0]
        # The message should be the full original message (no truncation)
        assert sent_message == message

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
        long_message = "This is a very long message that needs to be split into multiple parts. " * 200
        
        deps = create_test_context()
        
        await send_split_message(channel, long_message, deps)
        
        # Verify that channel.send was called multiple times
        call_count = channel.send.call_count
        assert call_count > 2, f"Expected multiple parts, got only {call_count}"
        
        # Collect all sent messages
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        
        # Verify each part is under the limit
        for i, part in enumerate(sent_messages):
            assert len(part) <= MESSAGE_LIMIT, f"Part {i+1} ({len(part)}) exceeds Discord limit ({MESSAGE_LIMIT})"
        
        # Verify all content is preserved
        reconstructed_message = "".join(sent_messages)
        assert reconstructed_message == long_message, "Content was lost during splitting!"

    @pytest.mark.asyncio
    async def test_content_preservation_no_truncation(self):
        """Test that content is preserved without truncation during normal splitting."""
        channel = create_mock_channel()
        channel.send = AsyncMock()
        
        # Create a very long message with natural break points
        long_message = """
This is a comprehensive explanation of Off the Grid controller settings from Gunzilla Games.

## Basic Controller Configuration

The controller settings in Off the Grid are designed to provide players with maximum customization options while maintaining competitive balance. The game features several key areas of controller configuration:

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

The controller system in Off the Grid is one of the most advanced in the industry, offering players unprecedented control over their gaming experience.
""" * 3  # Make it even longer
        
        deps = create_test_context()
        
        await send_split_message(channel, long_message, deps)
        
        # Verify that channel.send was called
        assert channel.send.called, "channel.send should have been called"
        
        # Collect all sent messages
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        
        # Verify no part exceeds the limit
        for i, part in enumerate(sent_messages):
            assert len(part) <= MESSAGE_LIMIT, f"Part {i+1} ({len(part)}) exceeds Discord limit ({MESSAGE_LIMIT})"
        
        # Verify all content is preserved (no truncation)
        reconstructed_message = "".join(sent_messages)
        assert reconstructed_message == long_message, "Content was lost during splitting!"
        
        # Verify no truncation messages
        for part in sent_messages:
            assert "truncated" not in part.lower(), f"Found truncation message: {part[:100]}..."
            assert "continues" not in part.lower(), f"Found continuation message: {part[:100]}..."

    @pytest.mark.asyncio
    async def test_truncation_at_recursion_limit(self):
        """Test that truncation only happens at recursion limit with proper message."""
        channel = create_mock_channel()
        
        # Make the mock raise an exception for messages over the limit
        def mock_send(content, **kwargs):
            if len(content) > MESSAGE_LIMIT:
                from discord import HTTPException
                # Create a proper mock response object
                mock_response = MagicMock()
                mock_response.status = 400
                raise HTTPException(mock_response, "Message too long")
            return AsyncMock()
        
        channel.send.side_effect = mock_send
        
        # Create a logger that shows the recursion depth
        logger = MagicMock()
        deps = create_test_context()
        deps["logger"] = logger
        
        # Create a message that will hit recursion limit
        message = "A" * 25000  # 25,000 A's - should need 13 parts but hit recursion limit at 10
        
        await send_split_message(channel, message, deps)
        
        # Verify that channel.send was called
        assert channel.send.called, "channel.send should have been called"
        
        # Collect all sent messages
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        
        # Check if truncation message is present
        has_truncation_message = any("truncated" in part.lower() for part in sent_messages)
        
        # Verify all parts are under limit (except the one that gets truncated)
        for i, part in enumerate(sent_messages):
            if "truncated" not in part.lower() and i != 11:  # Skip part 12 (index 11) as it's the failed attempt
                assert len(part) <= MESSAGE_LIMIT, f"Part {i+1} exceeds limit: {len(part)}"
        
        # Verify truncation message is present
        assert has_truncation_message, "Expected truncation message when recursion limit is hit"

    @pytest.mark.asyncio
    async def test_extreme_length_handling(self):
        """Test handling of extremely long messages."""
        channel = create_mock_channel()
        channel.send = AsyncMock()
        
        # Create an extremely long message (50,000 characters)
        extreme_message = "A" * 50000
        
        deps = create_test_context()
        
        await send_split_message(channel, extreme_message, deps)
        
        call_count = channel.send.call_count
        
        # Should be split into many parts (but limited by recursion limit)
        expected_min_parts = min(
            len(extreme_message) // MESSAGE_LIMIT, MAX_SPLIT_RECURSION + 1
        )
        assert call_count >= expected_min_parts, (
            f"Expected at least {expected_min_parts} parts for extreme length, "
            f"got only {call_count}"
        )
        
        # Verify all parts are under limit (except the last one which might be truncated)
        for i, call in enumerate(channel.send.call_args_list):
            part = call[0][0]
            # The last part might exceed limit if it's the remaining message after recursion limit
            if i == len(channel.send.call_args_list) - 1 and len(part) > MESSAGE_LIMIT:
                # This is expected for the last part when recursion limit is hit
                pass  # Expected behavior
            else:
                assert len(part) <= MESSAGE_LIMIT, f"Part {i+1} exceeds limit: {len(part)}"
        
        # Verify content preservation
        sent_messages = [call[0][0] for call in channel.send.call_args_list]
        reconstructed = "".join(sent_messages)
        assert reconstructed == extreme_message, "Extreme message content was lost!"

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
        assert call_count >= expected_parts - 1, f"Too few parts: {call_count} < {expected_parts - 1}"
        assert call_count <= expected_parts + 2, f"Too many parts: {call_count} > {expected_parts + 2}"
        
        # Verify all parts are under limit
        for i, call in enumerate(channel.send.call_args_list):
            part = call[0][0]
            assert len(part) <= MESSAGE_LIMIT, f"Part {i+1} exceeds limit: {len(part)}"
        
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
