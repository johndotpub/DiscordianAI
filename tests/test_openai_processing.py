import pytest
from unittest.mock import MagicMock, patch
import logging
import asyncio
from src.openai_processing import process_input_message

@pytest.mark.asyncio
async def test_process_input_message_normal():
    mock_user = MagicMock()
    mock_user.id = 1
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    class FakeMessage:
        def __init__(self, content):
            self.content = content
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

    response = await process_input_message(
        "Hello!",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        FakeOpenAIClient(),
        "gpt-4o-mini",
        "You are a helpful assistant.",
        8000,
    )
    assert response == "Test response"
    assert conversation_history[mock_user.id][-1]["role"] == "assistant"
    assert conversation_history[mock_user.id][-1]["content"] == "Test response"

@pytest.mark.asyncio
async def test_process_input_message_no_response():
    mock_user = MagicMock()
    mock_user.id = 2
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

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

    response = await process_input_message(
        "Hello!",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        FakeOpenAIClient(),
        "gpt-4o-mini",
        "You are a helpful assistant.",
        8000,
    )
    assert response == "Sorry, I didn't get that. Can you rephrase or ask again?"
    # Should not add assistant message to history
    assert mock_user.id not in conversation_history

@pytest.mark.asyncio
async def test_process_input_message_exception():
    mock_user = MagicMock()
    mock_user.id = 3
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    class FakeOpenAIClient:
        class Chat:
            class Completions:
                @staticmethod
                def create(*args, **kwargs):
                    raise Exception("API failure!")
            completions = Completions()
        chat = Chat()

    response = await process_input_message(
        "Hello!",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        FakeOpenAIClient(),
        "gpt-4o-mini",
        "You are a helpful assistant.",
        8000,
    )
    assert response == "Sorry, an error occurred while processing the message."
    # Should not add assistant message to history
    assert mock_user.id not in conversation_history

@pytest.mark.asyncio
async def test_process_input_message_to_thread_override():
    mock_user = MagicMock()
    mock_user.id = 4
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()
    called = {}

    class FakeMessage:
        def __init__(self, content):
            self.content = content
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
                    called["used"] = True
                    return FakeResponse("Threaded response")
            completions = Completions()
        chat = Chat()

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    response = await process_input_message(
        "Threaded!",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        FakeOpenAIClient(),
        "gpt-4o-mini",
        "You are a helpful assistant.",
        8000,
        to_thread=fake_to_thread,
    )
    assert response == "Threaded response"
    assert called["used"] is True

@pytest.mark.asyncio
async def test_process_input_message_empty_input():
    mock_user = MagicMock()
    mock_user.id = 5
    conversation_history = {}
    conversation_summary = []
    logger = MagicMock()

    class FakeMessage:
        def __init__(self, content):
            self.content = content
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
                    return FakeResponse("")
            completions = Completions()
        chat = Chat()

    response = await process_input_message(
        "",
        mock_user,
        conversation_summary,
        conversation_history,
        logger,
        FakeOpenAIClient(),
        "gpt-4o-mini",
        "You are a helpful assistant.",
        8000,
    )
    # Even if the API returns an empty string, it should be treated as no response
    assert response == "Sorry, I didn't get that. Can you rephrase or ask again?"
