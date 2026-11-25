# Comprehensive tests for conversation_manager.py functionality
import threading
from unittest.mock import patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager


class _Clock:
    """Controllable clock for cleanup cadence tests."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestThreadSafeConversationManager:
    """Test ThreadSafeConversationManager with comprehensive thread safety coverage."""

    def _assert_conversation_equal(self, actual, expected):
        """Helper method to assert two conversations are equal."""
        assert len(actual) == len(expected), f"Length mismatch: {len(actual)} != {len(expected)}"
        for i, (actual_msg, expected_msg) in enumerate(zip(actual, expected, strict=False)):
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

        assert manager.get_stats()["total_users"] == 0
        assert manager.get_stats()["active_locks"] == 0

        for index in range(101):
            manager.add_message(12345, "user", f"message-{index}")

        assert len(manager.get_conversation(12345)) == 100

    def test_init_with_custom_params(self):
        """Test initialization with non-default custom parameters."""
        clock = _Clock()
        manager = ThreadSafeConversationManager(
            max_history_per_user=7,
            cleanup_interval=1800,
            clock=clock,
        )

        for index in range(8):
            manager.add_message(12345, "user", f"message-{index}")

        conversation = manager.get_conversation(12345)
        assert len(conversation) == 7
        assert conversation[0]["content"] == "message-1"

        manager.begin_bot_turn(conversation_key="dm:67890")
        assert manager.cleanup_inactive_user_locks(force=False) == 0
        clock.advance(1800)
        assert manager.cleanup_inactive_user_locks(force=False) == 1

    def test_concurrent_messages_reuse_one_conversation_lock(self):
        """Concurrent writes for one conversation do not lose messages."""
        manager = ThreadSafeConversationManager()

        threads = [
            threading.Thread(target=manager.add_message, args=(12345, "user", f"m-{index}"))
            for index in range(10)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(manager.get_conversation(12345)) == 10
        assert manager.get_stats()["active_locks"] == 1

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

        metadata = {"ai_service": "openai", "model": "gpt-5-mini"}
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
        assert conversation[0]["content"] == "Message 2"
        assert conversation[1]["content"] == "Message 3"
        assert conversation[2]["content"] == "Message 4"  # Latest

    def test_get_recent_ai_service(self):
        """Test getting recent AI service from metadata."""
        manager = ThreadSafeConversationManager()

        # Add messages with different AI services
        manager.add_message(
            12345,
            "assistant",
            "OpenAI response",
            metadata={"ai_service": "openai"},
        )
        manager.add_message(
            12345,
            "assistant",
            "Perplexity response",
            metadata={"ai_service": "perplexity"},
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
            12345,
            "assistant",
            "Recent response",
            metadata={"ai_service": "openai"},
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

        manager.add_message(12345, "user", "Hello")
        manager.begin_bot_turn(conversation_key="dm:67890")
        manager.begin_bot_turn(conversation_key="dm:11111")

        cleaned_count = manager.cleanup_inactive_user_locks(force=True)

        assert cleaned_count == 2
        assert manager.get_stats()["active_locks"] == 1
        assert manager.get_conversation(12345)
        assert manager.get_conversation(conversation_key="dm:67890") == []

    def test_cleanup_inactive_user_locks_timing(self):
        """Test that cleanup respects timing intervals."""
        clock = _Clock()
        manager = ThreadSafeConversationManager(cleanup_interval=1000, clock=clock)

        manager.begin_bot_turn(conversation_key="dm:12345")

        assert manager.cleanup_inactive_user_locks(force=False) == 0

        clock.advance(1000)
        assert manager.cleanup_inactive_user_locks(force=False) == 1

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

        # Stored state should be unaffected
        assert manager.get_conversation(12345)[0]["content"] == "Hello"

    def test_background_cleanup_failure_handling(self):
        """Test handling of background cleanup failures."""
        manager = ThreadSafeConversationManager()

        with patch.object(
            manager,
            "cleanup_inactive_user_locks",
            side_effect=Exception("Cleanup error"),
        ):
            # Should handle cleanup failure gracefully
            result = manager.get_conversation(12345)
            assert result == []  # Should still work despite cleanup failure
