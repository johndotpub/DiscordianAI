# Import necessary libraries and modules for testing
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.openai_processing import process_openai_message


# Test the process_openai_message function for various scenarios
class TestProcessOpenAIMessage:
    @pytest.mark.asyncio
    async def test_process_normal_message(self):
        with patch(
            "src.conversation_manager.ThreadSafeConversationManager."
            "get_conversation_summary_formatted",
            return_value=[],
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
            conversation_manager = ThreadSafeConversationManager()
            logger = logging.getLogger("test_logger")

            response = await process_openai_message(
                input_message,
                mock_user,
                [],
                conversation_manager,
                logger,
                FakeOpenAIClient(),
                "gpt-5-mini",
                "You are a helpful assistant.",
                8000,
            )
            assert response == "Test response"

    @pytest.mark.asyncio
    async def test_process_message_no_response(self):
        # Clear caches to ensure test isolation
        from src.caching import conversation_cache, response_cache

        conversation_cache.clear()
        response_cache.cache.clear()

        with patch(
            "src.conversation_manager.ThreadSafeConversationManager."
            "get_conversation_summary_formatted",
            return_value=[],
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
            conversation_manager = ThreadSafeConversationManager()
            logger = logging.getLogger("test_logger")

            response = await process_openai_message(
                input_message,
                mock_user,
                [],
                conversation_manager,
                logger,
                FakeOpenAIClient(),
                "gpt-5-mini",
                "You are a helpful assistant.",
                8000,
            )
            assert response is None  # Updated to match new function behavior

    @pytest.mark.asyncio
    async def test_process_message_exception(self):
        with patch(
            "src.conversation_manager.ThreadSafeConversationManager."
            "get_conversation_summary_formatted",
            return_value=[],
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
            conversation_manager = ThreadSafeConversationManager()
            logger = logging.getLogger("test_logger")

            response = await process_openai_message(
                input_message,
                mock_user,
                [],
                conversation_manager,
                logger,
                FakeOpenAIClient(),
                "gpt-5-mini",
                "You are a helpful assistant.",
                8000,
            )
            assert response is None  # Updated to match new function behavior


# Explanation of what the tests are testing for:
# 1. `test_process_normal_message`: Tests that a normal input message is processed correctly and
#    returns the expected response from the OpenAI API.
# 2. `test_process_message_no_response`: Tests the function's behavior when the OpenAI API returns
#    an empty list of choices, simulating no response.
# 3. `test_process_message_exception`: Tests how the function handles exceptions, such as network
#    errors or unexpected issues with the OpenAI API.
