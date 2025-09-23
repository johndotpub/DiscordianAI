"""
Shared test utilities for DiscordianAI tests.

This module contains common fake classes and helper functions used across
multiple test files to eliminate duplication and maintain DRY principles.
"""

from unittest.mock import AsyncMock


class FakeResponse:
    """Fake response object for API testing."""

    def __init__(self, content="Test response", citations=None):
        self.choices = [FakeChoice(content)]
        if citations is not None:
            self.citations = citations


class FakeChoice:
    """Fake choice object for API testing."""

    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeMessage:
    """Fake message object for API testing."""

    def __init__(self, content):
        self.content = content


class FakeOpenAIClient:
    """Fake OpenAI client for testing."""

    def __init__(self, response_text="Test response", should_raise=False, return_none=False):
        self.response_text = response_text
        self.should_raise = should_raise
        self.return_none = return_none
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **_kwargs):
                if self.client.should_raise:
                    raise Exception("Test exception")
                if self.client.return_none:
                    return FakeResponse("")
                return FakeResponse(self.client.response_text)


class FakePerplexityClient:
    """Fake Perplexity client for testing."""

    def __init__(self, response_text="Test response", citations=None):
        self.response_text = response_text
        self.citations = citations or []
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, client):
            self.client = client
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            async def create(self, *_args, **_kwargs):
                return FakeResponse(self.client.response_text, citations=self.client.citations)


def create_mock_user(user_id=12345, username="testuser", display_name="Test User"):
    """Create a mock Discord user for testing."""
    user = AsyncMock()
    user.id = user_id
    user.name = username
    user.display_name = display_name
    user.mention = f"<@{user_id}>"
    return user


def create_mock_channel(channel_id=67890, name="test-channel"):
    """Create a mock Discord channel for testing."""
    channel = AsyncMock()
    channel.id = channel_id
    channel.name = name
    channel.mention = f"<#{channel_id}>"
    return channel


def create_mock_message(content="test message", user=None, channel=None):
    """Create a mock Discord message for testing."""
    message = AsyncMock()
    message.content = content
    message.author = user or create_mock_user()
    message.channel = channel or create_mock_channel()
    message.mentions = []
    message.embeds = []
    return message


def create_test_context(user_id=12345, username="testuser", display_name="Test User"):
    """Create a complete test context with user, conversation manager, and logger."""
    from unittest.mock import MagicMock

    from src.conversation_manager import ThreadSafeConversationManager

    user = create_mock_user(user_id, username, display_name)
    conversation_manager = ThreadSafeConversationManager()
    logger = MagicMock()

    return {"user": user, "conversation_manager": conversation_manager, "logger": logger}


def create_openai_response(content="Test response from OpenAI", finish_reason="stop"):
    """Create a mock OpenAI API response."""
    from unittest.mock import Mock

    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = content
    mock_response.choices[0].finish_reason = finish_reason
    mock_response.id = "chatcmpl-test123"
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 25
    mock_response.usage.completion_tokens = 15
    mock_response.usage.total_tokens = 40

    return mock_response


def create_perplexity_response(content="Test response from Perplexity", citations=None):
    """Create a mock Perplexity API response."""
    from unittest.mock import Mock

    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = content
    mock_response.choices[0].finish_reason = "stop"
    mock_response.id = "pplx-test123"
    mock_response.usage = Mock()
    mock_response.usage.prompt_tokens = 30
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 50

    if citations:
        mock_response.citations = citations

    return mock_response


# Common test data constants
TEST_USER_IDS = [12345, 67890, 99999, 11111, 22222]
TEST_MESSAGES = [
    "Hello, how are you?",
    "What's the weather like?",
    "Tell me about artificial intelligence",
    "Write a poem about cats",
    "What's happening in the news today?",
]
TEST_RESPONSES = {
    "openai": "This is a test response from OpenAI",
    "perplexity": "This is a test response from Perplexity [1]",
    "hybrid": "This is a hybrid response combining both sources",
}
