from src.conversations import get_conversation_summary


def test_get_conversation_summary():
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]
    expected_summary = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]
    summary = get_conversation_summary(conversation)
    assert summary == expected_summary


def test_get_conversation_summary_unmatched_user():
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
    ]
    expected_summary = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
    ]
    summary = get_conversation_summary(conversation)
    assert summary == expected_summary


def test_get_conversation_summary_empty():
    assert get_conversation_summary([]) == []
