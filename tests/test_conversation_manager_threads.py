# Comprehensive tests for conversation_manager.py functionality
import threading
from unittest.mock import patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager


class TestThreadSafeConversationManager:
    """Test ThreadSafeConversationManager with comprehensive thread safety coverage."""

    def _assert_conversation_equal(self, actual, expected):
        """Helper method to assert two conversations are equal."""
        assert len(actual) == len(expected), f"Length mismatch: {len(actual)} != {len(expected)}"
        for i, (actual_msg, expected_msg) in enumerate(zip(actual, expected)):
            assert actual_msg["role"] == expected_msg["role"], f"Role mismatch at index {i}"
            assert (
                actual_msg["content"] == expected_msg["content"]
            ), f"Content mismatch at index {i}"
            # Check metadata if present
            if "metadata" in expected_msg:
                assert "metadata" in actual_msg, f"Missing metadata at index {i}"
                assert (
                    actual_msg["metadata"] == expected_msg["metadata"]
                ), f"Metadata mismatch at index {i}"

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        manager = ThreadSafeConversationManager()

        assert manager._max_history == 50
        assert manager._cleanup_interval == 3600
        assert len(manager._conversations) == 0
        assert len(manager._user_locks) == 0

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        manager = ThreadSafeConversationManager(max_history_per_user=100, cleanup_interval=1800)

        assert manager._max_history == 100
        assert manager._cleanup_interval == 1800

    def test_get_user_lock(self):
        """Test user lock creation and retrieval."""
        manager = ThreadSafeConversationManager()

        # Get lock for user (should create new one)
        lock1 = manager._get_user_lock(12345)
        assert lock1 is not None
        assert hasattr(lock1, "acquire")
        assert hasattr(lock1, "release")

        # Get same lock again (should return same instance)
        lock2 = manager._get_user_lock(12345)
        assert lock1 is lock2

        # Get lock for different user (should create different lock)
        lock3 = manager._get_user_lock(67890)
        assert lock3 is not lock1

    def test_get_conversation_empty(self):
        """Test getting conversation for user with no history."""
        manager = ThreadSafeConversationManager()

        result = manager.get_conversation(12345)

        assert result == []
        assert isinstance(result, list)

    def test_add_message_valid_roles(self):
        """Test adding messages with valid roles."""
        manager = ThreadSafeConversationManager()

        # Test all valid roles
        manager.add_message(12345, "user", "Hello")
        manager.add_message(12345, "assistant", "Hi there!")
        manager.add_message(12345, "system", "System message")

        conversation = manager.get_conversation(12345)
        assert len(conversation) == 3
        assert conversation[0]["role"] == "user"
        assert conversation[0]["content"] == "Hello"
        assert conversation[1]["role"] == "assistant"
        assert conversation[1]["content"] == "Hi there!"
        assert conversation[2]["role"] == "system"
        assert conversation[2]["content"] == "System message"

    def test_add_message_with_metadata(self):
        """Test adding message with metadata."""
        manager = ThreadSafeConversationManager()

        metadata = {"ai_service": "openai", "model": "gpt-4"}
        manager.add_message(12345, "assistant", "Response", metadata=metadata)

        conversation = manager.get_conversation(12345)
        assert len(conversation) == 1
        assert conversation[0]["metadata"] == metadata

    def test_add_message_invalid_role(self):
        """Test adding message with invalid role."""
        manager = ThreadSafeConversationManager()

        with pytest.raises(ValueError) as exc_info:
            manager.add_message(12345, "invalid_role", "Message")

        assert "Invalid role" in str(exc_info.value)

    def test_add_message_empty_content(self):
        """Test adding message with empty content."""
        manager = ThreadSafeConversationManager()

        # Should not add empty message
        manager.add_message(12345, "user", "")
        manager.add_message(12345, "user", "   ")  # Whitespace only

        conversation = manager.get_conversation(12345)
        assert len(conversation) == 0

    def test_add_message_history_pruning(self):
        """Test automatic history pruning when max limit exceeded."""
        manager = ThreadSafeConversationManager(max_history_per_user=3)

        # Add 5 messages (should keep only latest 3)
        for i in range(5):
            manager.add_message(12345, "user", f"Message {i}")

        conversation = manager.get_conversation(12345)
        assert len(conversation) == 3
        assert conversation[0]["content"] == "Message 2"  # Oldest kept
        assert conversation[1]["content"] == "Message 3"
        assert conversation[2]["content"] == "Message 4"  # Latest

    def test_update_conversation_valid(self):
        """Test updating entire conversation with valid data."""
        manager = ThreadSafeConversationManager()

        new_conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        manager.update_conversation(12345, new_conversation)

        result = manager.get_conversation(12345)
        self._assert_conversation_equal(result, new_conversation)

    def test_update_conversation_invalid_format(self):
        """Test updating conversation with invalid message format."""
        manager = ThreadSafeConversationManager()

        # Missing 'role' key
        invalid_conversation = [{"content": "Hello"}]

        with pytest.raises(ValueError) as exc_info:
            manager.update_conversation(12345, invalid_conversation)

        assert "missing 'role' or 'content'" in str(exc_info.value)

    def test_update_conversation_invalid_role(self):
        """Test updating conversation with invalid role."""
        manager = ThreadSafeConversationManager()

        invalid_conversation = [{"role": "invalid", "content": "Hello"}]

        with pytest.raises(ValueError) as exc_info:
            manager.update_conversation(12345, invalid_conversation)

        assert "Invalid role" in str(exc_info.value)

    def test_update_conversation_with_pruning(self):
        """Test conversation update with automatic pruning."""
        manager = ThreadSafeConversationManager(max_history_per_user=2)

        # Update with 4 messages (should keep only latest 2)
        long_conversation = [
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Resp 1"},
            {"role": "user", "content": "Msg 2"},
            {"role": "assistant", "content": "Resp 2"},
        ]

        manager.update_conversation(12345, long_conversation)

        result = manager.get_conversation(12345)
        assert len(result) == 2
        assert result[0]["content"] == "Msg 2"  # Latest 2 kept
        assert result[1]["content"] == "Resp 2"

    def test_clear_conversation(self):
        """Test clearing user's conversation."""
        manager = ThreadSafeConversationManager()

        # Add some messages
        manager.add_message(12345, "user", "Hello")
        manager.add_message(12345, "assistant", "Hi")

        # Clear conversation
        cleared_count = manager.clear_conversation(12345)

        assert cleared_count == 2
        assert manager.get_conversation(12345) == []

    def test_clear_conversation_empty(self):
        """Test clearing empty conversation."""
        manager = ThreadSafeConversationManager()

        cleared_count = manager.clear_conversation(12345)

        assert cleared_count == 0

    def test_get_conversation_summary(self):
        """Test getting conversation summary."""
        manager = ThreadSafeConversationManager()

        # Add test messages
        manager.add_message(12345, "user", "Hello")
        manager.add_message(12345, "assistant", "Hi there!")
        manager.add_message(12345, "user", "How are you?")
        manager.add_message(12345, "assistant", "I'm doing well!")

        count, last_user, last_assistant = manager.get_conversation_summary(12345)

        assert count == 4
        assert last_user == "How are you?"
        assert last_assistant == "I'm doing well!"

    def test_get_conversation_summary_empty(self):
        """Test getting summary for empty conversation."""
        manager = ThreadSafeConversationManager()

        count, last_user, last_assistant = manager.get_conversation_summary(12345)

        assert count == 0
        assert last_user is None
        assert last_assistant is None

    def test_get_recent_ai_service(self):
        """Test getting recent AI service from metadata."""
        manager = ThreadSafeConversationManager()

        # Add messages with different AI services
        manager.add_message(
            12345, "assistant", "OpenAI response", metadata={"ai_service": "openai"}
        )
        manager.add_message(
            12345, "assistant", "Perplexity response", metadata={"ai_service": "perplexity"}
        )

        # Should return most recent service
        recent_service = manager.get_recent_ai_service(12345)
        assert recent_service == "perplexity"

    def test_get_recent_ai_service_no_metadata(self):
        """Test getting recent AI service when no metadata available."""
        manager = ThreadSafeConversationManager()

        manager.add_message(12345, "assistant", "Response without metadata")

        recent_service = manager.get_recent_ai_service(12345)
        assert recent_service is None

    def test_get_recent_ai_service_with_lookback(self):
        """Test AI service detection with lookback limit."""
        manager = ThreadSafeConversationManager()

        # Add more messages than lookback limit
        for i in range(10):
            manager.add_message(12345, "user", f"Message {i}")

        # Add one assistant message in range
        manager.add_message(
            12345, "assistant", "Recent response", metadata={"ai_service": "openai"}
        )

        # Should find the service within lookback range
        recent_service = manager.get_recent_ai_service(12345, lookback_messages=5)
        assert recent_service == "openai"

    def test_get_conversation_summary_formatted(self):
        """Test formatted conversation summary generation."""
        manager = ThreadSafeConversationManager()

        # Add test conversation
        manager.add_message(12345, "user", "Hello")
        manager.add_message(12345, "assistant", "Hi there!")
        manager.add_message(12345, "user", "How are you?")
        manager.add_message(12345, "assistant", "I'm good!")
        manager.add_message(12345, "user", "Great!")

        formatted = manager.get_conversation_summary_formatted(12345)

        # Should pair messages correctly
        assert len(formatted) == 5  # 4 paired + 1 unpaired user message
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"
        assert formatted[4]["role"] == "user"  # Unpaired message at end

    def test_get_conversation_summary_formatted_empty(self):
        """Test formatted summary for empty conversation."""
        manager = ThreadSafeConversationManager()

        formatted = manager.get_conversation_summary_formatted(12345)

        assert formatted == []

    def test_get_all_user_ids(self):
        """Test getting all user IDs with conversations."""
        manager = ThreadSafeConversationManager()

        # Add conversations for different users
        manager.add_message(12345, "user", "Hello")
        manager.add_message(67890, "user", "Hi there")

        user_ids = manager.get_all_user_ids()

        assert len(user_ids) == 2
        assert 12345 in user_ids
        assert 67890 in user_ids

    def test_get_stats(self):
        """Test getting conversation manager statistics."""
        manager = ThreadSafeConversationManager()

        # Add test data
        manager.add_message(12345, "user", "Hello")
        manager.add_message(12345, "assistant", "Hi")
        manager.add_message(67890, "user", "Test")

        stats = manager.get_stats()

        assert stats["total_users"] == 2
        assert stats["total_messages"] == 3
        assert stats["average_messages_per_user"] == 1.5
        assert stats["active_locks"] >= 2  # At least 2 user locks created

    def test_cleanup_inactive_user_locks(self):
        """Test cleanup of inactive user locks."""
        manager = ThreadSafeConversationManager()

        # Create locks for users
        manager._get_user_lock(12345)
        manager._get_user_lock(67890)
        manager._get_user_lock(11111)

        # Add conversation for only one user
        manager.add_message(12345, "user", "Hello")

        # Force cleanup
        cleaned_count = manager.cleanup_inactive_user_locks(force=True)

        # Should clean up locks for users without conversations
        assert cleaned_count == 2  # 67890 and 11111 locks cleaned
        assert 12345 in manager._user_locks  # Should keep active user lock

    def test_cleanup_inactive_user_locks_timing(self):
        """Test that cleanup respects timing intervals."""
        manager = ThreadSafeConversationManager(cleanup_interval=1000)  # Long interval

        # Create and cleanup locks
        manager._get_user_lock(12345)

        # Should not clean up if interval not reached (force=False)
        cleaned_count = manager.cleanup_inactive_user_locks(force=False)
        assert cleaned_count == 0  # No cleanup due to timing

    def test_thread_safety_concurrent_access(self):
        """Test thread safety with concurrent access."""
        manager = ThreadSafeConversationManager()

        def add_messages(user_id, start_num):
            for i in range(10):
                manager.add_message(user_id, "user", f"Message {start_num + i}")

        # Create multiple threads adding messages concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=add_messages, args=(12345, i * 10))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all messages were added safely
        conversation = manager.get_conversation(12345)
        assert len(conversation) == 50  # 5 threads * 10 messages each

    def test_deep_copy_isolation(self):
        """Test that returned conversations are deep copies."""
        manager = ThreadSafeConversationManager()

        manager.add_message(12345, "user", "Hello")

        # Get conversation copy
        conv1 = manager.get_conversation(12345)
        conv2 = manager.get_conversation(12345)

        # Modify one copy
        conv1[0]["content"] = "Modified"

        # Other copy should be unaffected
        assert conv2[0]["content"] == "Hello"

        # Original internal state should be unaffected
        internal_conv = manager._conversations[12345]
        assert internal_conv[0]["content"] == "Hello"

    def test_background_cleanup_failure_handling(self):
        """Test handling of background cleanup failures."""
        manager = ThreadSafeConversationManager()

        with patch.object(
            manager, "cleanup_inactive_user_locks", side_effect=Exception("Cleanup error")
        ):
            # Should handle cleanup failure gracefully
            result = manager.get_conversation(12345)
            assert result == []  # Should still work despite cleanup failure
