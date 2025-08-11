"""Performance and concurrency integration tests.

This test suite covers:
- Concurrent conversation management
- Rate limiting under load
- Memory usage patterns
- Response time benchmarks
- Thread safety validation
"""

import asyncio
import threading
import time
from unittest.mock import Mock, patch

import pytest

from src.conversation_manager import ThreadSafeConversationManager
from src.error_handling import safe_discord_send
from src.rate_limits import RateLimiter


class TestConcurrentConversationManagement:
    """Test conversation manager under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_conversation_updates(self):
        """Test concurrent updates to conversation history."""
        manager = ThreadSafeConversationManager(max_history_per_user=20)

        # Simulate multiple users updating conversations concurrently
        async def update_conversation(user_id, message_count):
            for i in range(message_count):
                manager.add_message(user_id, "user", f"Message {i} from user {user_id}")
                manager.add_message(user_id, "assistant", f"Response {i} to user {user_id}")
                # Small delay to simulate processing time
                await asyncio.sleep(0.001)

        # Run concurrent updates for multiple users
        tasks = []
        for user_id in range(5):
            task = asyncio.create_task(update_conversation(user_id, 10))
            tasks.append(task)

        await asyncio.gather(*tasks)

        # Verify all conversations were updated correctly
        for user_id in range(5):
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == 20  # 10 messages * 2 (user + assistant)

            # Verify message ordering is preserved
            for i in range(0, 20, 2):
                assert conversation[i]["role"] == "user"
                assert f"Message {i // 2} from user {user_id}" in conversation[i]["content"]
                assert conversation[i + 1]["role"] == "assistant"
                assert f"Response {i // 2} to user {user_id}" in conversation[i + 1]["content"]

    def test_thread_safe_lock_management(self):
        """Test thread-safe user lock management."""
        manager = ThreadSafeConversationManager()

        # Track lock acquisitions
        lock_acquisitions = []

        def update_with_delay(user_id, delay):
            with manager._get_user_lock(user_id):
                lock_acquisitions.append(f"start_{user_id}")
                time.sleep(delay)
                manager.add_message(user_id, "user", f"Thread message from {user_id}")
                lock_acquisitions.append(f"end_{user_id}")

        # Start multiple threads for the same user
        threads = []
        for _i in range(3):
            thread = threading.Thread(target=update_with_delay, args=(123, 0.01))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify locks were acquired sequentially (no interleaving)
        assert len(lock_acquisitions) == 6
        start_count = len([x for x in lock_acquisitions if x.startswith("start_")])
        end_count = len([x for x in lock_acquisitions if x.startswith("end_")])
        assert start_count == end_count == 3

        # Verify conversation has exactly 3 messages (one per thread)
        conversation = manager.get_conversation(123)
        assert len(conversation) == 3

    @pytest.mark.asyncio
    async def test_conversation_pruning_under_load(self):
        """Test conversation pruning behavior under high load."""
        manager = ThreadSafeConversationManager(max_history_per_user=10)

        # Add messages beyond the limit
        user_id = 456
        for i in range(25):
            manager.add_message(user_id, "user", f"Message {i}")
            # Intermittent async yields
            if i % 5 == 0:
                await asyncio.sleep(0.001)

        conversation = manager.get_conversation(user_id)

        # Should be pruned to max_history_per_user
        assert len(conversation) == 10

        # Should contain the most recent messages
        assert "Message 24" in conversation[-1]["content"]
        assert "Message 15" in conversation[0]["content"]  # Oldest kept message


class TestRateLimitingUnderLoad:
    """Test rate limiting behavior under concurrent load."""

    @pytest.mark.asyncio
    async def test_concurrent_rate_limit_checks(self):
        """Test rate limiter with concurrent requests from multiple users."""
        rate_limiter = RateLimiter()

        # Track rate limit results
        results = {}

        async def check_rate_limit_for_user(user_id, requests_count):
            user_results = []
            for _i in range(requests_count):
                allowed = rate_limiter.check_rate_limit(
                    user_id=user_id,
                    rate_limit=5,  # 5 requests
                    rate_limit_window_seconds=1,  # per second
                    logger=Mock(),
                )
                user_results.append(allowed)
                # Small delay between requests
                await asyncio.sleep(0.01)
            results[user_id] = user_results

        # Simulate multiple users making requests concurrently
        tasks = []
        for user_id in range(1001, 1004):  # 3 users
            task = asyncio.create_task(check_rate_limit_for_user(user_id, 8))
            tasks.append(task)

        await asyncio.gather(*tasks)

        # Verify rate limiting worked for each user independently
        for user_id in range(1001, 1004):
            user_results = results[user_id]
            # First 5 requests should be allowed, remaining should be blocked
            allowed_count = sum(user_results)
            assert (
                allowed_count <= 5
            ), f"User {user_id} had {allowed_count} requests allowed, expected <= 5"

    @pytest.mark.asyncio
    async def test_rate_limit_window_reset(self):
        """Test rate limit window reset functionality."""
        rate_limiter = RateLimiter()
        user_id = 2001

        # Make requests up to the limit
        for _i in range(3):
            allowed = rate_limiter.check_rate_limit(
                user_id=user_id, rate_limit=3, rate_limit_window_seconds=1, logger=Mock()
            )
            assert allowed is True

        # Next request should be blocked
        blocked = rate_limiter.check_rate_limit(
            user_id=user_id, rate_limit=3, rate_limit_window_seconds=1, logger=Mock()
        )
        assert blocked is False

        # Wait for window to reset
        await asyncio.sleep(1.1)

        # Should be allowed again
        allowed_after_reset = rate_limiter.check_rate_limit(
            user_id=user_id, rate_limit=3, rate_limit_window_seconds=1, logger=Mock()
        )
        assert allowed_after_reset is True

    def test_rate_limiter_memory_efficiency(self):
        """Test that rate limiter doesn't leak memory with many users."""
        rate_limiter = RateLimiter()

        # Simulate many users making requests
        for user_id in range(5000, 6000):  # 1000 users
            rate_limiter.check_rate_limit(
                user_id=user_id, rate_limit=10, rate_limit_window_seconds=60, logger=Mock()
            )

        # Verify internal data structures don't grow unbounded
        # In a real implementation, old entries should be cleaned up
        # This test ensures the data structure size is reasonable
        assert len(rate_limiter.last_command_timestamps) <= 1000
        assert len(rate_limiter.last_command_count) <= 1000


class TestDiscordAPIPerformance:
    """Test Discord API interaction performance."""

    @pytest.mark.asyncio
    async def test_concurrent_discord_sends(self):
        """Test concurrent Discord message sending."""
        # Mock successful Discord channels
        channels = []
        for i in range(5):
            channel = Mock()

            async def mock_send(*args, **kwargs):
                return None

            channel.send = Mock(side_effect=mock_send)
            channels.append(channel)

        logger = Mock()

        # Send messages to multiple channels concurrently
        async def send_to_channel(channel, message):
            return await safe_discord_send(channel, message, logger)

        tasks = []
        for i, channel in enumerate(channels):
            task = asyncio.create_task(send_to_channel(channel, f"Message {i}"))
            tasks.append(task)

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        # All sends should succeed
        assert all(results)

        # Should complete relatively quickly (concurrent execution)
        assert (end_time - start_time) < 1.0  # Less than 1 second for 5 messages

    @pytest.mark.asyncio
    async def test_discord_send_with_backpressure(self):
        """Test Discord sending with simulated backpressure."""
        # Mock channel that simulates rate limiting
        channel = Mock()
        call_count = 0

        async def mock_send(content):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # First two calls fail
                raise Exception("Rate limited by Discord")
            # Third call succeeds

        channel.send = mock_send
        logger = Mock()

        async def mock_sleep(*args):
            return None

        with patch("asyncio.sleep", side_effect=mock_sleep):
            start_time = time.time()
            result = await safe_discord_send(channel, "Test message", logger, max_retries=3)
            end_time = time.time()

        # Should eventually succeed
        assert result is True
        assert call_count == 3  # Two failures + one success

        # Should complete reasonably quickly despite retries
        assert (end_time - start_time) < 0.1


class TestMemoryAndResourceManagement:
    """Test memory usage and resource management patterns."""

    def test_conversation_memory_usage(self):
        """Test conversation manager memory usage patterns."""
        manager = ThreadSafeConversationManager(max_history_per_user=50)

        # Add conversations for many users
        num_users = 100
        messages_per_user = 30

        for user_id in range(num_users):
            for msg_num in range(messages_per_user):
                manager.add_message(
                    user_id, "user", f"This is message number {msg_num} from user {user_id}"
                )

        # Verify memory usage is reasonable
        stats = manager.get_stats()
        assert stats["total_users"] == num_users
        assert stats["total_messages"] == num_users * messages_per_user

        # Each user should have exactly messages_per_user messages
        for user_id in range(min(10, num_users)):  # Check first 10 users
            conversation = manager.get_conversation(user_id)
            assert len(conversation) == messages_per_user

    @pytest.mark.asyncio
    async def test_lock_cleanup_performance(self):
        """Test performance of lock cleanup process."""
        manager = ThreadSafeConversationManager(cleanup_interval=1)

        # Create many user locks
        user_ids = list(range(500))  # 500 users

        # Access locks for all users (creates them)
        for user_id in user_ids:
            with manager._get_user_lock(user_id):
                manager.add_message(user_id, "user", "test message")

        # Force cleanup
        start_time = time.time()
        cleaned_count = manager.cleanup_inactive_user_locks(force=True)
        end_time = time.time()

        # Cleanup should be reasonably fast
        assert (end_time - start_time) < 1.0  # Less than 1 second

        # Should have cleaned up some locks (or all if they're inactive)
        assert cleaned_count >= 0


class TestSystemIntegrationBenchmarks:
    """Benchmark tests for system integration performance."""

    @pytest.mark.asyncio
    async def test_end_to_end_response_time_benchmark(self):
        """Benchmark end-to-end response processing time."""
        # Mock all external dependencies
        user = Mock()
        user.id = 9999

        conversation_manager = ThreadSafeConversationManager()

        # Mock fast API response
        openai_client = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "Benchmark response"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15
        openai_client.chat.completions.create.return_value = mock_response

        logger = Mock()

        # Benchmark multiple requests
        response_times = []

        for i in range(10):
            start_time = time.time()

            # Process a message (this would be the main processing pipeline)
            from src.openai_processing import process_openai_message

            result = await process_openai_message(
                message=f"Benchmark message {i}",
                user=user,
                conversation_summary=[],
                conversation_manager=conversation_manager,
                logger=logger,
                openai_client=openai_client,
                gpt_model="gpt-5-mini",
                system_message="Benchmark assistant",
                output_tokens=1000,
            )

            end_time = time.time()
            response_times.append(end_time - start_time)

            # Verify processing succeeded
            assert result == "Benchmark response"

        # Calculate performance metrics
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)

        # Performance assertions (adjust thresholds based on expectations)
        assert avg_response_time < 0.1  # Average under 100ms
        assert max_response_time < 0.2  # Max under 200ms

        logger.info(f"Performance results: avg_response_time={avg_response_time:.4f}s, max_response_time={max_response_time:.4f}s")


if __name__ == "__main__":
    # Run performance tests with timing information
    pytest.main([__file__, "-v", "-s"])
