# Comprehensive tests for bot.py functionality
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.bot import (
    _process_message_core,
    adjust_for_code_block,
    find_split_index,
    initialize_bot_and_dependencies,
    process_channel_message,
    process_dm_message,
    register_event_handlers,
    send_split_message,
)


# Test bot initialization and dependency injection
class TestBotInitialization:
    def test_initialize_with_openai_only(self):
        """Test bot initialization with only OpenAI API key."""
        config = {
            "LOG_LEVEL": "INFO",
            "OPENAI_API_KEY": "test-openai-key",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_KEY": None,
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "MAX_HISTORY_PER_USER": 50,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
            "ALLOWED_CHANNELS": ["general"],
            "BOT_PRESENCE": "online",
            "ACTIVITY_TYPE": "listening",
            "ACTIVITY_STATUS": "for messages",
            "DISCORD_TOKEN": "test-token",
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "GPT_MODEL": "gpt-5-mini",
            "SYSTEM_MESSAGE": "Test assistant",
            "OUTPUT_TOKENS": 1000,
        }

        with patch("src.bot.get_connection_pool_manager") as mock_pool_manager:
            # Mock the connection pool manager methods
            mock_pool = mock_pool_manager.return_value
            mock_pool.create_openai_client.return_value = "mock_openai_client"
            mock_pool.create_perplexity_client.return_value = "mock_perplexity_client"

            deps = initialize_bot_and_dependencies(config)

            assert "logger" in deps
            assert "bot" in deps
            assert "client" in deps
            assert "perplexity_client" in deps
            assert deps["client"] is not None
            assert deps["perplexity_client"] is None
            assert "rate_limiter" in deps
            assert "conversation_manager" in deps
            mock_pool.create_openai_client.assert_called_once()

    def test_initialize_with_perplexity_only(self):
        """Test bot initialization with only Perplexity API key."""
        config = {
            "LOG_LEVEL": "INFO",
            "OPENAI_API_KEY": None,
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_KEY": "test-perplexity-key",
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "MAX_HISTORY_PER_USER": 50,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
            "ALLOWED_CHANNELS": ["general"],
            "BOT_PRESENCE": "online",
            "ACTIVITY_TYPE": "listening",
            "ACTIVITY_STATUS": "for messages",
            "DISCORD_TOKEN": "test-token",
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "GPT_MODEL": "gpt-5-mini",
            "SYSTEM_MESSAGE": "Test assistant",
            "OUTPUT_TOKENS": 1000,
        }

        with patch("src.bot.get_connection_pool_manager") as mock_pool_manager:
            # Mock the connection pool manager methods
            mock_pool = mock_pool_manager.return_value
            mock_pool.create_openai_client.return_value = "mock_openai_client"
            mock_pool.create_perplexity_client.return_value = "mock_perplexity_client"

            deps = initialize_bot_and_dependencies(config)

            assert deps["client"] is None
            assert deps["perplexity_client"] is not None
            mock_pool.create_perplexity_client.assert_called_once()

    def test_initialize_hybrid_mode(self):
        """Test bot initialization with both API keys."""
        config = {
            "LOG_LEVEL": "INFO",
            "OPENAI_API_KEY": "test-openai-key",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_KEY": "test-perplexity-key",
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "MAX_HISTORY_PER_USER": 50,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
            "ALLOWED_CHANNELS": ["general"],
            "BOT_PRESENCE": "online",
            "ACTIVITY_TYPE": "listening",
            "ACTIVITY_STATUS": "for messages",
            "DISCORD_TOKEN": "test-token",
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "GPT_MODEL": "gpt-5-mini",
            "SYSTEM_MESSAGE": "Test assistant",
            "OUTPUT_TOKENS": 1000,
        }

        with patch("src.bot.get_connection_pool_manager") as mock_pool_manager:
            # Mock the connection pool manager methods
            mock_pool = mock_pool_manager.return_value
            mock_pool.create_openai_client.return_value = "mock_openai_client"
            mock_pool.create_perplexity_client.return_value = "mock_perplexity_client"

            deps = initialize_bot_and_dependencies(config)

            assert deps["client"] is not None
            assert deps["perplexity_client"] is not None
            assert mock_pool.create_openai_client.call_count == 1
            assert mock_pool.create_perplexity_client.call_count == 1

    def test_initialize_no_api_keys_raises_error(self):
        """Test that missing both API keys raises ValueError."""
        config = {
            "LOG_LEVEL": "INFO",
            "OPENAI_API_KEY": None,
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_KEY": None,
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "MAX_HISTORY_PER_USER": 50,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
        }

        with pytest.raises(ValueError) as exc_info:
            initialize_bot_and_dependencies(config)

        assert "No API keys provided" in str(exc_info.value)

    def test_initialize_openai_client_failure(self):
        """Test handling of OpenAI client initialization failure."""
        config = {
            "LOG_LEVEL": "INFO",
            "OPENAI_API_KEY": "invalid-key",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
            "PERPLEXITY_API_KEY": None,
            "PERPLEXITY_API_URL": "https://api.perplexity.ai",
            "MAX_HISTORY_PER_USER": 50,
            "USER_LOCK_CLEANUP_INTERVAL": 3600,
        }

        with patch("src.bot.get_connection_pool_manager") as mock_pool_manager:
            # Mock the connection pool manager to raise an exception
            mock_pool = mock_pool_manager.return_value
            mock_pool.create_openai_client.side_effect = Exception("API Error")

            with pytest.raises(Exception) as exc_info:
                initialize_bot_and_dependencies(config)

            assert "OpenAI client initialization failed" in str(exc_info.value)


# Test message processing core functionality
class TestMessageProcessing:
    @pytest.mark.asyncio
    async def test_process_message_core_dm(self):
        """Test core message processing for DMs."""
        # Create mock message
        message = MagicMock(spec=discord.Message)
        message.author.name = "TestUser"
        message.author.id = 12345
        message.author.mention = "<@12345>"
        message.content = "Hello bot!"
        message.channel = MagicMock(spec=discord.DMChannel)
        message.channel.send = AsyncMock()

        # Create mock dependencies
        deps = {
            "logger": logging.getLogger("test"),
            "rate_limiter": MagicMock(),
            "conversation_manager": MagicMock(),
            "client": MagicMock(),
            "perplexity_client": MagicMock(),
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "GPT_MODEL": "gpt-5-mini",
            "SYSTEM_MESSAGE": "Test",
            "OUTPUT_TOKENS": 1000,
            "config": {},
        }

        # Mock successful rate limit check and response generation
        with (
            patch("src.bot.check_rate_limit", return_value=True),
            patch("src.bot.get_smart_response", return_value=("Test response", False, None)),
            patch("src.bot.send_formatted_message") as mock_send,
        ):

            deps["conversation_manager"].get_conversation_summary_formatted.return_value = []

            await _process_message_core(message, deps, is_dm=True)

            mock_send.assert_called_once()
            assert mock_send.call_args[0][1] == "Test response"  # Check response content

    @pytest.mark.asyncio
    async def test_process_message_core_rate_limited(self):
        """Test message processing when rate limited."""
        message = MagicMock(spec=discord.Message)
        message.author.name = "TestUser"
        message.author.id = 12345
        message.author.mention = "<@12345>"
        message.content = "Hello bot!"
        message.channel = MagicMock()
        message.channel.send = AsyncMock()

        deps = {
            "logger": logging.getLogger("test"),
            "rate_limiter": MagicMock(),
            "conversation_manager": MagicMock(),
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
        }

        # Mock rate limit failure
        with patch("src.bot.check_rate_limit", return_value=False):
            await _process_message_core(message, deps, is_dm=True)

            message.channel.send.assert_called_once()
            sent_message = message.channel.send.call_args[0][0]
            assert "rate limit" in sent_message.lower()

    @pytest.mark.asyncio
    async def test_process_message_core_channel(self):
        """Test core message processing for channel messages."""
        message = MagicMock(spec=discord.Message)
        message.author.name = "TestUser"
        message.author.id = 12345
        message.author.mention = "<@12345>"
        message.content = "<@123> Hello bot!"
        message.channel = MagicMock(spec=discord.TextChannel)
        message.channel.name = "general"
        message.channel.send = AsyncMock()

        deps = {
            "logger": logging.getLogger("test"),
            "rate_limiter": MagicMock(),
            "conversation_manager": MagicMock(),
            "client": MagicMock(),
            "perplexity_client": MagicMock(),
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
            "GPT_MODEL": "gpt-5-mini",
            "SYSTEM_MESSAGE": "Test",
            "OUTPUT_TOKENS": 1000,
            "REASONING_EFFORT": None,
            "VERBOSITY": None,
            "config": {},
        }

        with (
            patch("src.bot.check_rate_limit", return_value=True),
            patch("src.bot.get_smart_response", return_value=("Test response", False, None)),
            patch("src.bot.send_formatted_message") as mock_send,
        ):

            deps["conversation_manager"].get_conversation_summary_formatted.return_value = []

            await _process_message_core(message, deps, is_dm=False)

            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_core_exception_handling(self):
        """Test exception handling in message processing."""
        message = MagicMock(spec=discord.Message)
        message.author.name = "TestUser"
        message.author.id = 12345
        message.content = "Hello bot!"
        message.channel = MagicMock()
        message.channel.send = AsyncMock()

        deps = {
            "logger": logging.getLogger("test"),
            "rate_limiter": MagicMock(),
            "conversation_manager": MagicMock(),
            "RATE_LIMIT": 10,
            "RATE_LIMIT_PER": 60,
        }

        # Mock rate limit check to raise exception
        with patch("src.bot.check_rate_limit", side_effect=Exception("Test error")):
            await _process_message_core(message, deps, is_dm=True)

            # Should send error message
            message.channel.send.assert_called_once()
            sent_message = message.channel.send.call_args[0][0]
            assert "error" in sent_message.lower()

    @pytest.mark.asyncio
    async def test_process_dm_message(self):
        """Test DM message processing wrapper."""
        message = MagicMock(spec=discord.Message)
        deps = {"test": "deps"}

        with patch("src.bot._process_message_core") as mock_core:
            await process_dm_message(message, deps)
            mock_core.assert_called_once_with(message, deps, is_dm=True)

    @pytest.mark.asyncio
    async def test_process_channel_message(self):
        """Test channel message processing wrapper."""
        message = MagicMock(spec=discord.Message)
        deps = {"test": "deps"}

        with patch("src.bot._process_message_core") as mock_core:
            await process_channel_message(message, deps)
            mock_core.assert_called_once_with(message, deps, is_dm=False)


# Test message splitting functionality
class TestMessageSplitting:
    def test_find_split_index_with_newline(self):
        """Test finding split index with newline available."""
        message = "Hello world\nThis is a test\nAnother line"
        middle = len(message) // 2
        result = find_split_index(message, middle)

        assert result > 0
        assert result <= middle
        assert message[result] == "\n" or message[result - 1] == "\n"

    def test_find_split_index_no_newline(self):
        """Test finding split index with no newline available."""
        message = "This is a very long message with no newlines at all"
        middle = len(message) // 2
        result = find_split_index(message, middle)

        assert result == middle

    def test_adjust_for_code_block_inside(self):
        """Test code block adjustment when split is inside code block."""
        message = "Text before\n```\ncode block\nmore code\n```\nText after"
        before_split = "Text before\n```\ncode"
        middle = len(before_split)

        result_before, result_after = adjust_for_code_block(message, before_split, middle)

        # Should adjust to preserve code block
        assert "```" in result_before
        assert len(result_before) >= len(before_split)
        assert result_before + result_after == message

    def test_adjust_for_code_block_outside(self):
        """Test code block adjustment when split is outside code block."""
        message = "Text before code block and text after"
        before_split = "Text before"
        middle = len(before_split)

        result_before, result_after = adjust_for_code_block(message, before_split, middle)

        # Should not adjust since we're not in a code block
        assert result_before == before_split
        assert result_after == message[len(before_split) :]

    @pytest.mark.asyncio
    async def test_send_split_message_short(self):
        """Test sending short message that doesn't need splitting."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        message = "Short message"
        deps = {"logger": logging.getLogger("test")}

        await send_split_message(channel, message, deps)

        channel.send.assert_called_once_with(message, suppress_embeds=False)

    @pytest.mark.asyncio
    async def test_send_split_message_long(self):
        """Test sending long message that needs splitting."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Message longer than 2000 characters
        message = "x" * 2500
        deps = {"logger": logging.getLogger("test")}

        await send_split_message(channel, message, deps)

        # Should be called twice (for split message)
        assert channel.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_split_message_recursion_limit(self):
        """Test recursion limit protection in message splitting."""
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Very long message that would cause deep recursion
        message = "x" * 5000  # Long message with no natural split points
        deps = {"logger": logging.getLogger("test")}

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
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "API Error"))

        message = "Test message"
        deps = {"logger": logging.getLogger("test")}

        with pytest.raises(discord.HTTPException):
            await send_split_message(channel, message, deps)


# Test event handler registration
class TestEventHandlers:
    def test_register_event_handlers(self):
        """Test that event handlers are properly registered."""
        bot = MagicMock(spec=discord.Client)
        deps = {
            "logger": logging.getLogger("test"),
            "BOT_PRESENCE": "online",
            "ACTIVITY_TYPE": "listening",
            "ACTIVITY_STATUS": "for messages",
            "ALLOWED_CHANNELS": ["general"],
        }

        register_event_handlers(bot, deps)

        # Verify that bot.event was called to register handlers
        assert bot.event.call_count >= 4  # Should register multiple event handlers

    @pytest.mark.asyncio
    async def test_on_ready_handler(self):
        """Test the on_ready event handler functionality."""
        bot = MagicMock(spec=discord.Client)
        bot.user.name = "TestBot"
        bot.user.id = 12345
        bot.guilds = [MagicMock(), MagicMock()]  # Mock 2 guilds
        bot.change_presence = AsyncMock()

        deps = {
            "logger": logging.getLogger("test"),
            "BOT_PRESENCE": "online",
            "ACTIVITY_TYPE": "listening",
            "ACTIVITY_STATUS": "for messages",
            "ALLOWED_CHANNELS": ["general"],
        }

        with patch("src.bot.set_activity_status") as mock_activity:
            register_event_handlers(bot, deps)

            # Get the registered on_ready handler
            on_ready_calls = [
                call for call in bot.event.call_args_list if call[0][0].__name__ == "on_ready"
            ]
            assert len(on_ready_calls) > 0

            # Execute the on_ready handler
            on_ready_handler = on_ready_calls[0][0][0]
            await on_ready_handler()

            # Verify presence was set
            bot.change_presence.assert_called_once()
            mock_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_message_handler_dm(self):
        """Test the on_message handler for DMs."""
        bot = MagicMock(spec=discord.Client)
        bot.user = MagicMock()
        bot.user.id = 99999

        deps = {"logger": logging.getLogger("test"), "ALLOWED_CHANNELS": ["general"]}

        # Create mock DM
        message = MagicMock(spec=discord.Message)
        message.author = MagicMock()
        message.author.id = 12345  # Different from bot
        message.channel = MagicMock(spec=discord.DMChannel)

        with patch("src.bot.process_dm_message") as mock_dm:
            register_event_handlers(bot, deps)

            # Get the on_message handler
            on_message_calls = [
                call for call in bot.event.call_args_list if call[0][0].__name__ == "on_message"
            ]
            assert len(on_message_calls) > 0

            # Execute the on_message handler
            on_message_handler = on_message_calls[0][0][0]
            await on_message_handler(message)

            mock_dm.assert_called_once_with(message, deps)

    @pytest.mark.asyncio
    async def test_on_message_handler_ignores_self(self):
        """Test that on_message ignores bot's own messages."""
        bot = MagicMock(spec=discord.Client)
        bot.user = MagicMock()
        bot.user.id = 12345

        deps = {"logger": logging.getLogger("test"), "ALLOWED_CHANNELS": ["general"]}

        # Create message from bot itself
        message = MagicMock(spec=discord.Message)
        message.author = bot.user  # Same as bot user

        with (
            patch("src.bot.process_dm_message") as mock_dm,
            patch("src.bot.process_channel_message") as mock_channel,
        ):

            register_event_handlers(bot, deps)

            # Execute the on_message handler
            on_message_calls = [
                call for call in bot.event.call_args_list if call[0][0].__name__ == "on_message"
            ]
            on_message_handler = on_message_calls[0][0][0]
            await on_message_handler(message)

            # Should not process messages from self
            mock_dm.assert_not_called()
            mock_channel.assert_not_called()


class TestBotMessageHandling:
    """Test the bot's actual message handling to prevent duplication issues."""

    @pytest.mark.asyncio
    async def test_send_formatted_message_no_duplication_with_embed(self):
        """Test that send_formatted_message prevents duplicate content when embed_data exists."""
        # Mock channel
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # Mock embed data
        embed = MagicMock(spec=discord.Embed)
        embed.description = "Test embed content with citations"
        embed_data = {
            "embed": embed,
            "citations": {"1": "https://example.com", "2": "https://test.com"},
            "clean_text": "Content with [1] and [2] citations",
            "embed_metadata": {
                "was_truncated": False,
                "original_length": 50,
                "formatted_length": 50,
            },
        }

        # This message text should NOT be sent - only the embed should be sent
        message = "This raw text should not appear in Discord"
        deps = {"logger": MagicMock()}

        # Import and test the function directly
        from src.bot import send_formatted_message

        await send_formatted_message(channel, message, deps, embed_data=embed_data)

        # Verify exactly one message is sent
        assert channel.send.call_count == 1

        # Verify it's sent with empty message text and embed
        call_args = channel.send.call_args
        assert call_args[0][0] == ""  # Empty message text
        assert call_args[1]["embed"] == embed  # Embed is sent

        # Verify the raw message text was NOT sent
        assert message not in str(call_args)
        assert "raw text should not appear" not in str(call_args)

    @pytest.mark.asyncio
    async def test_send_formatted_message_regular_message_without_embed(self):
        """Test that send_formatted_message sends regular message when no embed_data is present."""
        # Mock channel
        channel = MagicMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        # No embed data
        embed_data = None
        message = "Hello! This is a regular message without citations."
        deps = {"logger": MagicMock()}

        # Import and test the function directly
        from src.bot import send_formatted_message

        await send_formatted_message(channel, message, deps, embed_data=embed_data)

        # Verify exactly one message is sent
        assert channel.send.call_count == 1

        # Verify it's sent with the regular message text
        call_args = channel.send.call_args
        assert message in call_args[0][0]  # Message text is sent
        assert "embed" not in call_args[1]  # No embed
