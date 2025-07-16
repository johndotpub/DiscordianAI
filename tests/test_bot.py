# Import necessary libraries and modules for testing
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

# Pytest library for testing
import pytest

# Import the module to be tested
import src.bot as bot


# Test the process_input_message function for various scenarios
class TestProcessInputMessage:
    # Test processing a normal message
    @pytest.mark.asyncio
    async def test_process_normal_message(self):
        with (
            patch("src.bot.get_conversation_summary", return_value=[]),
            patch("src.bot.logger") as mock_logger,
        ):
            class FakeMessage:
                def __init__(self, content):
                    self.content = content
                def strip(self):
                    return self.content.strip()
            class FakeChoice:
                def __init__(self, content):
                    self.message = FakeMessage(content)
            class FakeResponse:
                def __init__(self, content):
                    self.choices = [FakeChoice(content)]
            class FakeOpenAIClient:
                class Chat:
                    class Completions:
                        @staticmethod
                        def create(*args, **kwargs):
                            return FakeResponse("Test response")
                    completions = Completions()
                chat = Chat()
            mock_user = MagicMock()
            mock_user.id = 123
            input_message = "Hello"
            # Patch to_thread as an async function
            async def async_to_thread(f, *a, **kw):
                return f(*a, **kw)
            response = await bot.process_input_message(
                input_message, mock_user, [],
                client=FakeOpenAIClient(),
                to_thread=async_to_thread
            )
            assert response == "Test response"
            mock_logger.info.assert_any_call("Received response from the API.")

    # Test processing a message when OpenAI API returns no choices
    @pytest.mark.asyncio
    async def test_process_message_no_response(self):
        with (
            patch("src.bot.get_conversation_summary", return_value=[]),
            patch("src.bot.logger") as mock_logger,
        ):
            class FakeResponse:
                def __init__(self):
                    self.choices = []
            class FakeOpenAIClient:
                class Chat:
                    class Completions:
                        @staticmethod
                        def create(*args, **kwargs):
                            return FakeResponse()
                    completions = Completions()
                chat = Chat()
            mock_user = MagicMock()
            mock_user.id = 123
            input_message = "Hello"
            # Patch to_thread as an async function
            async def async_to_thread(f, *a, **kw):
                return f(*a, **kw)
            response = await bot.process_input_message(
                input_message, mock_user, [],
                client=FakeOpenAIClient(),
                to_thread=async_to_thread
            )
            assert response == "Sorry, I didn't get that. Can you rephrase or ask again?"
            mock_logger.error.assert_any_call("API error: No response text.")

    # Test processing a message when an exception occurs
    @pytest.mark.asyncio
    async def test_process_message_exception(self):
        with (
            patch("src.bot.get_conversation_summary", return_value=[]),
            patch("src.bot.logger") as mock_logger,
        ):
            class FakeOpenAIClient:
                class Chat:
                    class Completions:
                        @staticmethod
                        def create(*args, **kwargs):
                            raise Exception("Test exception")
                    completions = Completions()
                chat = Chat()
            mock_user = MagicMock()
            mock_user.id = 123
            input_message = "Hello"
            # Patch to_thread as an async function that mimics real threading by catching exceptions
            async def async_to_thread(f, *a, **kw):
                try:
                    return f(*a, **kw)
                except Exception as e:
                    # Mimic real asyncio.to_thread: propagate exception to the caller
                    raise e
            response = await bot.process_input_message(
                input_message, mock_user, [],
                client=FakeOpenAIClient(),
                to_thread=async_to_thread
            )
            assert response == "Sorry, an error occurred while processing the message."
            mock_logger.error.assert_any_call("Failed to get response from the API: Test exception")


# Explanation of what the tests are testing for:
# 1. `test_process_normal_message`: Tests that a normal input message is processed correctly and
#    returns the expected response from the OpenAI API.
# 2. `test_process_message_no_response`: Tests the function's behavior when the OpenAI API returns
#    an empty list of choices, simulating no response.
# 3. `test_process_message_exception`: Tests how the function handles exceptions, such as network
#    errors or unexpected issues with the OpenAI API.
