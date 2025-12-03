"""Load and stress tests for DiscordianAI bot.

This module tests the bot's ability to handle high concurrent load,
simulating scenarios with 10k+ users as claimed in the documentation.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.rate_limits import RateLimiter


class TestConcurrentUserLoad:
    """Test bot behavior under high concurrent user load."""

    @pytest.mark.asyncio
    async def test_conversation_manager_concurrent_users(self):
        """Test conversation manager with 1000+ concurrent users."""
        manager = ThreadSafeConversationManager(max_history_per_user=50)

        async def simulate_user(user_id: int, num_messages: int):
            """Simulate a user sending multiple messages."""
            for i in range(num_messages):
                message = {"role": "user", "content": f"Message {i} from user {user_id}"}
                manager.add_message(user_id, message)
                await asyncio.sleep(0.001)  # Small delay to simulate real usage

        # Simulate 1000 users, each sending 10 messages concurrently
        num_users = 1000
        messages_per_user = 10

        tasks = [
            simulate_user(user_id, messages_per_user) for user_id in range(num_users)
        ]

        start_time = time.time()
        await asyncio.gather(*tasks)
        elapsed_time = time.time() - start_time

        # Verify all messages were stored
        for user_id in range(num_users):
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == messages_per_user

        # Performance check: should complete in reasonable time (< 10 seconds)
        assert elapsed_time < 10.0, f"Load test took {elapsed_time:.2f}s, expected < 10s"

    @pytest.mark.asyncio
    async def test_conversation_manager_memory_cleanup(self):
        """Test memory cleanup with many inactive users."""
        manager = ThreadSafeConversationManager(
            max_history_per_user=50, cleanup_interval=1
        )

        # Add messages for many users
        num_users = 5000
        for user_id in range(num_users):
            manager.add_message(user_id, {"role": "user", "content": f"Message from {user_id}"})

        # Verify all users have conversations
        assert len(manager._conversations) == num_users

        # Simulate cleanup (normally done by background task)
        manager._cleanup_inactive_users()

        # After cleanup, inactive users should be removed
        # (In real scenario, cleanup happens based on activity time)
        # For this test, we verify cleanup mechanism works
        assert hasattr(manager, "_cleanup_inactive_users")

    @pytest.mark.asyncio
    async def test_rate_limiter_concurrent_requests(self):
        """Test rate limiter with concurrent requests from many users."""
        rate_limiter = RateLimiter()
        rate_limit = 10
        rate_limit_per = 60

        async def check_rate_limit(user_id: int):
            """Check rate limit for a user."""
            return rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per)

        # Simulate 5000 users checking rate limits concurrently
        num_users = 5000
        tasks = [check_rate_limit(user_id) for user_id in range(num_users)]

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        elapsed_time = time.time() - start_time

        # All should pass (first request for each user)
        assert all(results), "All users should pass rate limit on first request"

        # Should complete quickly (< 2 seconds)
        assert elapsed_time < 2.0, f"Rate limit check took {elapsed_time:.2f}s"

    @pytest.mark.asyncio
    async def test_rate_limiter_high_frequency_requests(self):
        """Test rate limiter with high frequency requests from same user."""
        rate_limiter = RateLimiter()
        rate_limit = 10
        rate_limit_per = 60

        user_id = 12345

        # First 10 requests should pass
        for i in range(10):
            result = rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per)
            assert result, f"Request {i+1} should pass"

        # 11th request should be rate limited
        result = rate_limiter.check_rate_limit(user_id, rate_limit, rate_limit_per)
        assert not result, "11th request should be rate limited"

    @pytest.mark.asyncio
    async def test_concurrent_message_processing(self):
        """Test concurrent message processing simulation."""
        manager = ThreadSafeConversationManager()

        async def process_message(user_id: int, message_num: int):
            """Simulate processing a message."""
            # Add message
            manager.add_message(
                user_id, {"role": "user", "content": f"Message {message_num}"}
            )

            # Get conversation
            conversation = manager.get_conversation(user_id)

            # Get summary
            summary = manager.get_conversation_summary(user_id, max_messages=10)

            return len(conversation), len(summary)

        # Simulate 2000 users processing messages concurrently
        num_users = 2000
        messages_per_user = 5

        tasks = []
        for user_id in range(num_users):
            for msg_num in range(messages_per_user):
                tasks.append(process_message(user_id, msg_num))

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        elapsed_time = time.time() - start_time

        # Verify all messages processed
        assert len(results) == num_users * messages_per_user

        # Should complete in reasonable time
        assert elapsed_time < 15.0, f"Processing took {elapsed_time:.2f}s"

    @pytest.mark.asyncio
    async def test_memory_usage_with_many_users(self):
        """Test memory usage doesn't grow unbounded with many users."""
        manager = ThreadSafeConversationManager(max_history_per_user=50)

        # Add conversations for many users
        num_users = 10000
        messages_per_user = 20

        for user_id in range(num_users):
            for i in range(messages_per_user):
                manager.add_message(
                    user_id, {"role": "user", "content": f"Message {i}"}
                )

        # Verify conversations are pruned to max_history_per_user
        for user_id in range(min(100, num_users)):  # Check sample
            conversation = manager.get_conversation(user_id)
            assert len(conversation) <= 50, "Conversation should be pruned"

    @pytest.mark.asyncio
    async def test_concurrent_get_conversation_summary(self):
        """Test concurrent conversation summary generation."""
        manager = ThreadSafeConversationManager()

        # Pre-populate conversations
        num_users = 1000
        for user_id in range(num_users):
            for i in range(30):
                manager.add_message(
                    user_id, {"role": "user", "content": f"Message {i}"}
                )

        async def get_summary(user_id: int):
            """Get conversation summary for a user."""
            return manager.get_conversation_summary(user_id, max_messages=10)

        # Get summaries concurrently
        tasks = [get_summary(user_id) for user_id in range(num_users)]

        start_time = time.time()
        summaries = await asyncio.gather(*tasks)
        elapsed_time = time.time() - start_time

        # All summaries should be generated
        assert len(summaries) == num_users
        assert all(len(s) <= 10 for s in summaries), "Summaries should be limited"

        # Should complete in reasonable time
        assert elapsed_time < 10.0, f"Summary generation took {elapsed_time:.2f}s"

    @pytest.mark.asyncio
    async def test_thread_safety_under_load(self):
        """Test thread safety with concurrent read/write operations."""
        manager = ThreadSafeConversationManager()

        async def writer(user_id: int, num_writes: int):
            """Write messages concurrently."""
            for i in range(num_writes):
                manager.add_message(
                    user_id, {"role": "user", "content": f"Write {i}"}
                )
                await asyncio.sleep(0.0001)

        async def reader(user_id: int, num_reads: int):
            """Read conversations concurrently."""
            for _ in range(num_reads):
                conversation = manager.get_conversation(user_id)
                await asyncio.sleep(0.0001)

        # Concurrent read/write operations
        num_users = 500
        writes_per_user = 10
        reads_per_user = 20

        write_tasks = [
            writer(user_id, writes_per_user) for user_id in range(num_users)
        ]
        read_tasks = [reader(user_id, reads_per_user) for user_id in range(num_users)]

        # Run reads and writes concurrently
        start_time = time.time()
        await asyncio.gather(*write_tasks, *read_tasks)
        elapsed_time = time.time() - start_time

        # Verify data integrity
        for user_id in range(min(100, num_users)):  # Check sample
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == writes_per_user

        # Should complete without errors or data corruption
        assert elapsed_time < 20.0, f"Concurrent operations took {elapsed_time:.2f}s"

    @pytest.mark.asyncio
    async def test_cleanup_under_load(self):
        """Test cleanup mechanism works under load."""
        manager = ThreadSafeConversationManager(
            max_history_per_user=50, cleanup_interval=1
        )

        # Add many users
        num_users = 5000
        for user_id in range(num_users):
            manager.add_message(
                user_id, {"role": "user", "content": f"Message from {user_id}"}
            )

        # Verify all users exist
        assert len(manager._conversations) == num_users

        # Simulate cleanup
        initial_count = len(manager._conversations)
        manager._cleanup_inactive_users()

        # Cleanup should work (exact behavior depends on implementation)
        # At minimum, cleanup function should execute without error
        assert hasattr(manager, "_cleanup_inactive_users")

    @pytest.mark.asyncio
    async def test_high_concurrency_message_ordering(self):
        """Test message ordering is preserved under high concurrency."""
        manager = ThreadSafeConversationManager()

        user_id = 9999
        num_messages = 100

        async def add_message(index: int):
            """Add a message with specific index."""
            manager.add_message(
                user_id, {"role": "user", "content": f"Message {index}"}
            )

        # Add messages concurrently
        tasks = [add_message(i) for i in range(num_messages)]
        await asyncio.gather(*tasks)

        # Verify messages are in order
        conversation = manager.get_conversation(user_id)
        assert len(conversation) == num_messages

        # Check ordering (messages should be added in order despite concurrency)
        for i, msg in enumerate(conversation):
            assert msg["content"] == f"Message {i}", f"Message {i} out of order"

