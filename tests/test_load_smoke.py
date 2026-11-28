"""Smoke tests for high concurrent user counts.

The scenarios exercise bookkeeping under many users; they make no timing
claims and assert only on stored state.
"""

import asyncio

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.rate_limits import RateLimiter


class TestConcurrentUserSmoke:
    """Exercise conversation and rate-limit bookkeeping under many users."""

    @pytest.mark.asyncio
    async def test_conversation_manager_concurrent_users(self):
        """Test conversation manager with 1000+ concurrent users."""
        manager = ThreadSafeConversationManager(max_history_per_user=50)

        async def simulate_user(user_id: int, num_messages: int):
            """Simulate a user sending multiple messages."""
            for i in range(num_messages):
                manager.add_message(user_id, "user", f"Message {i} from user {user_id}")
                await asyncio.sleep(0.001)  # Small delay to simulate real usage

        # Simulate 1000 users, each sending 10 messages concurrently
        num_users = 1000
        messages_per_user = 10

        tasks = [simulate_user(user_id, messages_per_user) for user_id in range(num_users)]

        await asyncio.gather(*tasks)

        # Verify all messages were stored
        for user_id in range(num_users):
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == messages_per_user

    @pytest.mark.asyncio
    async def test_conversation_manager_memory_cleanup(self):
        """Test memory cleanup with many inactive users."""
        manager = ThreadSafeConversationManager(max_history_per_user=50, cleanup_interval=1)

        # Add messages for many users
        num_users = 5000
        for user_id in range(num_users):
            manager.add_message(user_id, "user", f"Message from {user_id}")

        # Verify all users have conversations
        assert manager.get_stats()["total_users"] == num_users

        manager.begin_bot_turn(user_id=999_999)
        cleaned = manager.cleanup_inactive_user_locks(force=True)

        assert cleaned == 1
        assert manager.get_conversation(999_999) == []
        assert manager.get_stats()["active_locks"] == num_users
        assert manager.get_stats()["total_users"] == num_users

    @pytest.mark.asyncio
    async def test_rate_limiter_concurrent_requests(self):
        """Test rate limiter with concurrent requests from many users."""
        rate_limiter = RateLimiter()
        rate_limit = 10
        rate_limit_per = 60

        async def check_rate_limit(user_id: int):
            """Check rate limit for a user."""
            import logging

            logger = logging.getLogger(__name__)
            return rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per, logger)

        # Simulate 5000 users checking rate limits concurrently
        num_users = 5000
        tasks = [check_rate_limit(user_id) for user_id in range(num_users)]

        results = await asyncio.gather(*tasks)

        # All should pass (first request for each user)
        assert all(results), "All users should pass rate limit on first request"

    @pytest.mark.asyncio
    async def test_rate_limiter_high_frequency_requests(self):
        """Test rate limiter with high frequency requests from same user."""
        rate_limiter = RateLimiter()
        rate_limit = 10
        rate_limit_per = 60

        user_id = 12345

        import logging

        logger = logging.getLogger(__name__)

        # First 10 requests should pass
        for i in range(10):
            result = rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per, logger)
            assert result, f"Request {i + 1} should pass"

        # 11th request should be rate limited
        result = rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per, logger)
        assert not result, "11th request should be rate limited"

    @pytest.mark.asyncio
    async def test_concurrent_message_processing(self):
        """Test concurrent message processing simulation."""
        manager = ThreadSafeConversationManager()

        async def process_message(user_id: int, message_num: int):
            """Simulate processing a message."""
            # Add message
            manager.add_message(user_id, "user", f"Message {message_num}")

            # Get conversation
            conversation = manager.get_conversation(user_id)

            return len(conversation)

        # Simulate 2000 users processing messages concurrently
        num_users = 2000
        messages_per_user = 5

        tasks = [
            process_message(user_id, msg_num)
            for user_id in range(num_users)
            for msg_num in range(messages_per_user)
        ]

        results = await asyncio.gather(*tasks)

        # Verify all messages processed
        assert len(results) == num_users * messages_per_user

    @pytest.mark.asyncio
    async def test_memory_usage_with_many_users(self):
        """Test memory usage doesn't grow unbounded with many users."""
        manager = ThreadSafeConversationManager(max_history_per_user=50)

        # Add conversations for many users
        num_users = 10000
        messages_per_user = 20

        for user_id in range(num_users):
            for i in range(messages_per_user):
                manager.add_message(user_id, "user", f"Message {i}")

        # Verify conversations are pruned to max_history_per_user
        for user_id in range(min(100, num_users)):  # Check sample
            conversation = manager.get_conversation(user_id)
            assert len(conversation) <= 50, "Conversation should be pruned"

    @pytest.mark.asyncio
    async def test_thread_safety_with_concurrent_reads_and_writes(self):
        """Test thread safety with concurrent read/write operations."""
        manager = ThreadSafeConversationManager()

        async def writer(user_id: int, num_writes: int):
            """Write messages concurrently."""
            for i in range(num_writes):
                manager.add_message(user_id, "user", f"Write {i}")
                await asyncio.sleep(0.0001)

        async def reader(user_id: int, num_reads: int):
            """Read conversations concurrently."""
            for _ in range(num_reads):
                manager.get_conversation(user_id)  # Read operation
                await asyncio.sleep(0.0001)

        # Concurrent read/write operations
        num_users = 500
        writes_per_user = 10
        reads_per_user = 20

        write_tasks = [writer(user_id, writes_per_user) for user_id in range(num_users)]
        read_tasks = [reader(user_id, reads_per_user) for user_id in range(num_users)]

        # Run reads and writes concurrently
        await asyncio.gather(*write_tasks, *read_tasks)

        # Verify data integrity
        for user_id in range(min(100, num_users)):  # Check sample
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == writes_per_user
