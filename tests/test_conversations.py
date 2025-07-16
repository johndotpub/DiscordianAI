# Import the necessary modules for testing
import pytest

from conversations import get_conversation_summary

# The purpose of this test suite is to validate the functionality of the get_conversation_summary
# function from the conversations module. This function is expected to process a list of
# conversation messages, each represented as a dictionary with 'role' and 'content' keys, and
# return a summary of the conversation according to specific rules (e.g., handling alternating
# messages, non-alternating messages, empty conversations, conversations with only user or
# assistant messages, and invalid roles).


# Test for basic functionality with alternating user and assistant messages
def test_get_conversation_summary_basic():
    # Define a conversation with alternating messages between user and assistant
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]

    # The expected summary should include all messages in their original order
    expected_summary = conversation.copy()

    # Call the function and verify the output matches the expected summary
    assert get_conversation_summary(conversation) == expected_summary


# Test for handling non-alternating messages correctly
def test_get_conversation_summary_non_alternating():
    # Define a conversation with consecutive messages from the same role
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "user", "content": "It's me again."},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "assistant", "content": "Welcome back!"},
    ]

    # The expected summary should handle consecutive messages according to the function's logic
    # This example assumes the first message of each role is included
    expected_summary = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    # Verify the function's output
    assert get_conversation_summary(conversation) == expected_summary


# Test for an empty conversation
def test_get_conversation_summary_empty():
    # An empty conversation should result in an empty summary
    assert get_conversation_summary([]) == []


# Test for conversation with only user messages
def test_get_conversation_summary_user_only():
    # Define a conversation with only user messages
    conversation = [
        {"role": "user", "content": "Hello?"},
        {"role": "user", "content": "Anyone there?"},
    ]

    # The expected summary should include all user messages as there are no assistant messages
    expected_summary = conversation.copy()

    # Verify the function's output
    assert get_conversation_summary(conversation) == expected_summary


# Test for conversation with only assistant messages
def test_get_conversation_summary_assistant_only():
    # Define a conversation with only assistant messages
    conversation = [
        {"role": "assistant", "content": "Welcome!"},
        {"role": "assistant", "content": "How can I assist?"},
    ]

    # An empty summary is expected as there are no user messages to initiate the conversation
    expected_summary = []

    # Verify the function's output
    assert get_conversation_summary(conversation) == expected_summary


# Test for handling invalid role in conversation
def test_get_conversation_summary_invalid_role():
    # Define a conversation including an invalid role
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "unknown", "content": "This should not be included"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    # The expected summary should exclude messages with invalid roles
    expected_summary = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    # Verify the function's output
    assert get_conversation_summary(conversation) == expected_summary


# Parametrized tests to cover various scenarios with a single test function
@pytest.mark.parametrize(
    "conversation,expected_summary",
    [
        # Alternating messages
        (
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"},
            ],
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
                {"role": "assistant", "content": "I'm doing well, thank you!"},
            ],
        ),
        # Non-alternating messages
        (
            [
                {"role": "user", "content": "Hello"},
                {"role": "user", "content": "It's me again."},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "assistant", "content": "Welcome back!"},
            ],
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        ),
        # Empty conversation
        ([], []),
        # User messages only
        (
            [
                {"role": "user", "content": "Hello?"},
                {"role": "user", "content": "Anyone there?"},
            ],
            [
                {"role": "user", "content": "Hello?"},
                {"role": "user", "content": "Anyone there?"},
            ],
        ),
        # Assistant messages only
        (
            [
                {"role": "assistant", "content": "Welcome!"},
                {"role": "assistant", "content": "How can I assist?"},
            ],
            [],
        ),
        # Invalid role
        (
            [
                {"role": "user", "content": "Hello"},
                {"role": "unknown", "content": "This should not be included"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        ),
    ],
)
def test_get_conversation_summary_parametrized(conversation, expected_summary):
    # Verify the function's output for each parametrized test case
    assert get_conversation_summary(conversation) == expected_summary


# Test for exception handling
def test_get_conversation_summary_exception_handling():
    # Assuming the function raises ValueError for None input
    with pytest.raises(ValueError):
        get_conversation_summary(None)
