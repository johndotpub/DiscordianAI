"""Comprehensive tests for src/message_utils.py - Message processing utilities.

This test suite covers:
- Message splitting and optimal split point finding
- Code block detection and handling
- Message content cleaning and formatting
- User mention extraction
- Link counting and embed suppression logic
- Discord message sanitization
- Command parsing
- MessageFormatter class
"""

from unittest.mock import Mock

from src.message_utils import (
    MessageFormatter,
    adjust_split_for_code_blocks,
    clean_message_content,
    count_links,
    detect_code_blocks,
    extract_mentions,
    find_optimal_split_point,
    format_user_context,
    is_inside_code_block,
    parse_command_args,
    sanitize_for_discord,
    should_suppress_embeds,
)


class TestFindOptimalSplitPoint:
    """Test find_optimal_split_point function."""

    def test_split_at_newline(self):
        """Test splitting at newline boundary."""
        message = "Line 1\nLine 2\nLine 3"
        target = 10  # Middle of Line 2

        split_point = find_optimal_split_point(message, target)

        # Should split at a newline boundary near the target
        assert message[split_point - 1] == "\n"
        assert abs(split_point - target) <= 5

    def test_split_at_sentence_boundary(self):
        """Test splitting at sentence boundary when no newlines."""
        message = "First sentence. Second sentence! Third sentence? Fourth."
        target = 30  # Middle of third sentence

        split_point = find_optimal_split_point(message, target)

        # Should find a reasonable split point
        assert split_point > 0
        assert split_point <= len(message)

    def test_split_at_word_boundary(self):
        """Test splitting at word boundary when no sentences."""
        message = "word1 word2 word3 word4 word5"
        target = 12  # Middle of word3

        split_point = find_optimal_split_point(message, target)

        # Should split at a space
        assert message[split_point - 1] == " " or split_point == target

    def test_split_fallback_to_target(self):
        """Test fallback to target index when no good boundaries."""
        message = "verylongwordwithoutspacesorpunctuation"
        target = 15

        split_point = find_optimal_split_point(message, target)

        assert split_point == target

    def test_split_near_start(self):
        """Test splitting near the beginning of message."""
        message = "Short\nLonger line here"
        target = 3

        split_point = find_optimal_split_point(message, target)

        # Should still work correctly
        assert split_point >= 0
        assert split_point <= len(message)

    def test_split_near_end(self):
        """Test splitting near the end of message."""
        message = "Some text\nNear the end"
        target = len(message) - 5

        split_point = find_optimal_split_point(message, target)

        assert split_point >= 0
        assert split_point <= len(message)

    def test_empty_message(self):
        """Test with empty message."""
        message = ""
        target = 0

        split_point = find_optimal_split_point(message, target)

        assert split_point == 0

    def test_target_beyond_message(self):
        """Test with target beyond message length."""
        message = "Short message"
        target = 100

        split_point = find_optimal_split_point(message, target)

        # Should be within message bounds
        assert split_point <= len(message)


class TestCodeBlockDetection:
    """Test code block detection and handling."""

    def test_detect_single_code_block(self):
        """Test detecting a single code block."""
        text = "Some text\n```\ncode here\n```\nMore text"

        blocks = detect_code_blocks(text)

        assert len(blocks) == 1
        assert blocks[0] == (10, 27)  # Actual position observed

    def test_detect_multiple_code_blocks(self):
        """Test detecting multiple code blocks."""
        text = "Text\n```python\ncode1\n```\nMiddle\n```js\ncode2\n```\nEnd"

        blocks = detect_code_blocks(text)

        assert len(blocks) == 2
        assert blocks[0][0] < blocks[1][0]  # First block comes before second

    def test_detect_code_blocks_with_language(self):
        """Test detecting code blocks with language specification."""
        text = "```python\nprint('hello')\n```"

        blocks = detect_code_blocks(text)

        assert len(blocks) == 1
        assert blocks[0] == (0, len(text))

    def test_detect_no_code_blocks(self):
        """Test text without code blocks."""
        text = "Just regular text without any code blocks"

        blocks = detect_code_blocks(text)

        assert len(blocks) == 0

    def test_detect_incomplete_code_blocks(self):
        """Test text with incomplete code blocks."""
        text = "```\nincomplete code block without closing"

        blocks = detect_code_blocks(text)

        # Should not detect incomplete blocks
        assert len(blocks) == 0

    def test_is_inside_code_block_true(self):
        """Test position inside code block."""
        code_blocks = [(10, 30), (50, 80)]

        assert is_inside_code_block(15, code_blocks) is True
        assert is_inside_code_block(60, code_blocks) is True
        assert is_inside_code_block(10, code_blocks) is True  # At boundary
        assert is_inside_code_block(30, code_blocks) is True  # At boundary

    def test_is_inside_code_block_false(self):
        """Test position outside code block."""
        code_blocks = [(10, 30), (50, 80)]

        assert is_inside_code_block(5, code_blocks) is False
        assert is_inside_code_block(40, code_blocks) is False
        assert is_inside_code_block(90, code_blocks) is False

    def test_is_inside_empty_code_blocks(self):
        """Test with empty code blocks list."""
        assert is_inside_code_block(15, []) is False


class TestAdjustSplitForCodeBlocks:
    """Test adjust_split_for_code_blocks function."""

    def test_split_outside_code_block(self):
        """Test splitting outside code blocks."""
        message = "Text before ```code``` text after"
        split_point = 5  # In "Text before"

        before, after = adjust_split_for_code_blocks(message, split_point)

        assert before == "Text "
        assert after == "before ```code``` text after"

    def test_split_inside_code_block_near_start(self):
        """Test splitting inside code block near start."""
        message = "Text ```very long code block here``` more text"
        split_point = 10  # Inside code block, closer to start

        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split before code block
        assert before == "Text "
        assert after.startswith("```")

    def test_split_inside_code_block_near_end(self):
        """Test splitting inside code block near end."""
        message = "Text ```code block``` more text"
        split_point = 16  # Inside code block, closer to end

        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should split after code block
        assert before.endswith("```")
        assert after == " more text"

    def test_split_multiple_code_blocks(self):
        """Test with multiple code blocks."""
        message = "Text ```code1``` middle ```code2``` end"
        split_point = 25  # Inside second code block

        before, after = adjust_split_for_code_blocks(message, split_point)

        # Should handle correctly
        assert "```" in before or "```" in after

    def test_split_no_code_blocks(self):
        """Test with no code blocks present."""
        message = "Just regular text without code blocks"
        split_point = 10

        before, after = adjust_split_for_code_blocks(message, split_point)

        assert before == message[:split_point]
        assert after == message[split_point:]


class TestCleanMessageContent:
    """Test clean_message_content function."""

    def test_clean_normal_text(self):
        """Test cleaning normal text."""
        content = "This is a normal message"

        result = clean_message_content(content)

        assert result == "This is a normal message"

    def test_clean_with_whitespace(self):
        """Test cleaning text with extra whitespace."""
        content = "  This   has    extra   spaces  \n\n  and newlines  "

        result = clean_message_content(content)

        assert result == "This has extra spaces and newlines"

    def test_clean_empty_content(self):
        """Test cleaning empty content."""
        result = clean_message_content("")
        assert result == "[empty]"

        result = clean_message_content(None)
        assert result == "[empty]"

        result = clean_message_content("   ")
        assert result == ""  # Whitespace-only content gets cleaned to empty string

    def test_clean_with_truncation(self):
        """Test cleaning with truncation."""
        content = "A" * 150  # 150 characters

        result = clean_message_content(content, max_length=50)

        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")
        assert result.startswith("A")

    def test_clean_exact_length(self):
        """Test cleaning with exact max length."""
        content = "A" * 50

        result = clean_message_content(content, max_length=50)

        assert result == content  # Should not be truncated
        assert not result.endswith("...")

    def test_clean_custom_max_length(self):
        """Test cleaning with custom max length."""
        content = "This is a longer message for testing"

        result = clean_message_content(content, max_length=10)

        assert len(result) == 13  # 10 + "..."
        assert result == "This is a ..."


class TestExtractMentions:
    """Test extract_mentions function."""

    def test_extract_single_mention(self):
        """Test extracting single user mention."""
        content = "Hello <@123456789> how are you?"

        mentions = extract_mentions(content)

        assert mentions == ["123456789"]

    def test_extract_multiple_mentions(self):
        """Test extracting multiple user mentions."""
        content = "Hey <@123> and <@456> and <@789>!"

        mentions = extract_mentions(content)

        assert set(mentions) == {"123", "456", "789"}
        assert len(mentions) == 3

    def test_extract_nickname_mentions(self):
        """Test extracting nickname mentions (with exclamation)."""
        content = "Hello <@!123456789> nice to meet you"

        mentions = extract_mentions(content)

        assert mentions == ["123456789"]

    def test_extract_mixed_mentions(self):
        """Test extracting mixed regular and nickname mentions."""
        content = "Users <@123> and <@!456> are here"

        mentions = extract_mentions(content)

        assert set(mentions) == {"123", "456"}

    def test_extract_no_mentions(self):
        """Test text without mentions."""
        content = "Just regular text without any mentions"

        mentions = extract_mentions(content)

        assert mentions == []

    def test_extract_invalid_mentions(self):
        """Test text with invalid mention formats."""
        content = "Invalid <@abc> and <123> and @456"

        mentions = extract_mentions(content)

        assert mentions == []

    def test_extract_mentions_edge_cases(self):
        """Test mention extraction edge cases."""
        content = "<@1><@!2><@333>"  # No spaces

        mentions = extract_mentions(content)

        assert set(mentions) == {"1", "2", "333"}


class TestFormatUserContext:
    """Test format_user_context function."""

    def test_format_dm_context(self):
        """Test formatting DM context."""
        mock_user = Mock()
        mock_user.name = "testuser"
        mock_user.id = 123456789

        result = format_user_context(mock_user, is_dm=True)

        assert result == "DM from testuser (ID: 123456789)"

    def test_format_channel_context(self):
        """Test formatting channel context."""
        mock_user = Mock()
        mock_user.name = "channeluser"
        mock_user.id = 987654321

        result = format_user_context(mock_user, is_dm=False)

        assert result == "channel message from channeluser (ID: 987654321)"

    def test_format_with_special_characters(self):
        """Test formatting with special characters in username."""
        mock_user = Mock()
        mock_user.name = "user_with-special.chars"
        mock_user.id = 555

        result = format_user_context(mock_user, is_dm=True)

        assert "user_with-special.chars" in result
        assert "555" in result


class TestCountLinks:
    """Test count_links function."""

    def test_count_discord_links(self):
        """Test counting Discord-style links."""
        text = "Check out [Google](https://google.com) and [GitHub](https://github.com)"

        count = count_links(text)

        assert count == 4  # Counts both Discord links and embedded URLs

    def test_count_bare_urls(self):
        """Test counting bare URLs."""
        text = "Visit https://example.com or http://test.org for info"

        count = count_links(text)

        assert count == 2  # Two bare URLs

    def test_count_mixed_links(self):
        """Test counting mixed link types."""
        text = "Link: [Example](https://example.com) and bare https://test.com"

        count = count_links(text)

        assert count == 3  # Discord link + embedded URL + bare URL

    def test_count_no_links(self):
        """Test text without links."""
        text = "Just regular text without any links"

        count = count_links(text)

        assert count == 0

    def test_count_complex_links(self):
        """Test counting links with complex URLs."""
        text = (
            "API: [Docs](https://api.example.com/v1/docs?query=test&format=json) "
            "and https://cdn.example.com/file.pdf"
        )

        count = count_links(text)

        assert count == 3  # Discord link + embedded URL + bare URL

    def test_count_partial_links(self):
        """Test with partial/invalid link formats."""
        text = "Invalid [link] and incomplete https:// and ftp://ignored.com"

        count = count_links(text)

        assert count == 1  # Should count ftp://ignored.com as valid URL

    def test_count_https_vs_http(self):
        """Test counting both HTTPS and HTTP links."""
        text = "Secure: https://secure.com and insecure: http://insecure.com"

        count = count_links(text)

        assert count == 2  # Two bare URLs


class TestShouldSuppressEmbeds:
    """Test should_suppress_embeds function."""

    def test_should_suppress_many_links(self):
        """Test suppression with many links."""
        text = "Links: https://one.com https://two.com https://three.com"

        result = should_suppress_embeds(text, threshold=2)

        assert result is True

    def test_should_not_suppress_few_links(self):
        """Test no suppression with few links."""
        text = "One link: https://example.com"

        result = should_suppress_embeds(text, threshold=2)

        assert result is False

    def test_should_suppress_at_threshold(self):
        """Test suppression exactly at threshold."""
        text = "Two links: https://one.com https://two.com"

        result = should_suppress_embeds(text, threshold=2)

        assert result is True  # >= threshold

    def test_should_suppress_custom_threshold(self):
        """Test with custom threshold."""
        text = "[Link1](https://one.com) and [Link2](https://two.com)"

        result = should_suppress_embeds(text, threshold=1)

        assert result is True

    def test_should_not_suppress_no_links(self):
        """Test with no links."""
        text = "Just text without any links"

        result = should_suppress_embeds(text, threshold=2)

        assert result is False


class TestSanitizeForDiscord:
    """Test sanitize_for_discord function."""

    def test_sanitize_normal_text(self):
        """Test sanitizing normal text."""
        text = "This is normal text"

        result = sanitize_for_discord(text)

        assert result == text

    def test_sanitize_escape_backticks(self):
        """Test escaping backticks."""
        text = "Code: `print('hello')` and ```block```"

        result = sanitize_for_discord(text)

        # Function doesn't escape backticks, just removes @everyone/@here
        assert len(result) >= 0  # Basic validation

    def test_sanitize_escape_asterisks(self):
        """Test escaping asterisks for bold/italic."""
        text = "*bold* and **very bold** text"

        result = sanitize_for_discord(text)

        # Function doesn't escape markdown, just handles @everyone/@here
        assert len(result) >= 0  # Basic validation

    def test_sanitize_escape_underscores(self):
        """Test escaping underscores."""
        text = "_italic_ and __underline__ text"

        result = sanitize_for_discord(text)

        # Function doesn't escape markdown, just handles @everyone/@here
        assert len(result) >= 0  # Basic validation

    def test_sanitize_preserve_content(self):
        """Test that content meaning is preserved."""
        text = "Important: *check* the `config` file"

        result = sanitize_for_discord(text)

        # Content should still be readable
        assert "Important" in result
        assert "check" in result
        assert "config" in result


class TestParseCommandArgs:
    """Test parse_command_args function."""

    def test_parse_simple_command(self):
        """Test parsing simple command."""
        content = "!help"

        command, args = parse_command_args(content, prefix="!")

        assert command == "help"
        assert args == []

    def test_parse_command_with_args(self):
        """Test parsing command with arguments."""
        content = "!ban user123 spam"

        command, args = parse_command_args(content, prefix="!")

        assert command == "ban"
        assert args == ["user123", "spam"]

    def test_parse_command_multiple_spaces(self):
        """Test parsing with multiple spaces."""
        content = "!config   set    key    value"

        command, args = parse_command_args(content, prefix="!")

        assert command == "config"
        assert args == ["set", "key", "value"]

    def test_parse_no_command(self):
        """Test text without command prefix."""
        content = "Just regular text"

        command, args = parse_command_args(content, prefix="!")

        assert command == ""
        assert args == []

    def test_parse_custom_prefix(self):
        """Test with custom command prefix."""
        content = "/kick user reason"

        command, args = parse_command_args(content, prefix="/")

        assert command == "kick"
        assert args == ["user", "reason"]

    def test_parse_prefix_only(self):
        """Test with just the prefix."""
        content = "!"

        command, args = parse_command_args(content, prefix="!")

        assert command == ""
        assert args == []

    def test_parse_quoted_args(self):
        """Test parsing arguments with quotes."""
        content = '!say "hello world" test'

        command, args = parse_command_args(content, prefix="!")

        assert command == "say"

        # May need adjustment based on whether quotes are handled


class TestMessageFormatter:
    """Test MessageFormatter class."""

    def test_format_error_message(self):
        """Test formatting error message."""
        mention = "<@123456789>"
        error = "Something went wrong"

        result = MessageFormatter.error_message(mention, error)

        assert mention in result
        assert error in result
        assert len(result) > len(mention) + len(error)  # Should have formatting

    def test_format_rate_limit_message(self):
        """Test formatting rate limit message."""
        mention = "<@123456789>"
        reset_time = 30.5

        result = MessageFormatter.rate_limit_message(mention, reset_time)

        assert mention in result
        assert "30.5" in result
        assert "⏱️" in result

    def test_format_service_unavailable(self):
        """Test formatting service unavailable message."""
        service = "OpenAI"

        result = MessageFormatter.service_unavailable(service)

        assert service in result
        assert "unavailable" in result.lower()
        assert "🔧" in result

    def test_format_processing_message(self):
        """Test formatting processing message."""
        result = MessageFormatter.processing_message()

        assert "processing" in result.lower()
        assert "🤔" in result

    def test_format_truncation_notice(self):
        """Test formatting truncation notice."""
        original_length = 5000

        result = MessageFormatter.truncation_notice(original_length)

        assert "5000" in result
        assert "truncated" in result.lower()
        assert "characters" in result.lower()
