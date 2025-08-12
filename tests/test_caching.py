"""Tests for the caching and performance optimization system.

This test suite covers:
- ThreadSafeLRUCache functionality
- ResponseCache behavior and key generation
- Request deduplication logic
- Performance monitoring metrics
- Cache decorators and integration
"""

import asyncio
import time

import pytest

from src.caching import (
    CacheEntry,
    PerformanceMonitor,
    RequestDeduplicator,
    ResponseCache,
    ThreadSafeLRUCache,
    cached_response,
    cleanup_caches,
    deduplicated_request,
)


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_cache_entry_creation(self):
        """Test creating a cache entry."""
        entry = CacheEntry(value="test response", timestamp=time.time(), ttl=300.0)

        assert entry.value == "test response"
        assert entry.access_count == 0
        assert not entry.is_expired()

    def test_cache_entry_expiration(self):
        """Test cache entry expiration."""
        # Create expired entry
        old_timestamp = time.time() - 400  # 400 seconds ago
        entry = CacheEntry(
            value="expired response", timestamp=old_timestamp, ttl=300.0  # 300 second TTL
        )

        assert entry.is_expired()

    def test_cache_entry_touch(self):
        """Test cache entry touch functionality."""
        entry = CacheEntry(value="test", timestamp=time.time())

        initial_count = entry.access_count
        entry.touch()

        assert entry.access_count == initial_count + 1


class TestThreadSafeLRUCache:
    """Test ThreadSafeLRUCache implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.cache = ThreadSafeLRUCache(max_size=5, default_ttl=300.0)

    def test_cache_put_and_get(self):
        """Test basic cache put and get operations."""
        self.cache.put("key1", "value1")

        result = self.cache.get("key1")
        assert result == "value1"

    def test_cache_miss(self):
        """Test cache miss behavior."""
        result = self.cache.get("nonexistent")
        assert result is None

        stats = self.cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_cache_hit_stats(self):
        """Test cache hit statistics."""
        self.cache.put("key1", "value1")
        self.cache.get("key1")
        self.cache.get("key1")

        stats = self.cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 100.0

    def test_cache_size_limit(self):
        """Test cache size limit enforcement."""
        # Fill cache beyond max size
        for i in range(10):
            self.cache.put(f"key{i}", f"value{i}")

        # Should only have max_size entries
        stats = self.cache.get_stats()
        assert stats["size"] == 5
        assert stats["evictions"] == 5

        # First entries should have been evicted
        assert self.cache.get("key0") is None
        assert self.cache.get("key5") is not None

    def test_cache_ttl_expiration(self):
        """Test TTL-based expiration."""
        # Put entry with short TTL
        self.cache.put("expire_key", "expire_value", ttl=0.1)

        # Should be available immediately
        assert self.cache.get("expire_key") == "expire_value"

        # Wait for expiration
        time.sleep(0.2)

        # Should be expired now
        assert self.cache.get("expire_key") is None

    def test_cache_cleanup_expired(self):
        """Test cleanup of expired entries."""
        # Add entries with different TTLs
        self.cache.put("short", "value1", ttl=0.1)
        self.cache.put("long", "value2", ttl=300.0)

        # Wait for short TTL to expire
        time.sleep(0.2)

        # Cleanup expired entries
        expired_count = self.cache.cleanup_expired()

        assert expired_count == 1
        assert self.cache.get("short") is None
        assert self.cache.get("long") == "value2"

    def test_cache_clear(self):
        """Test clearing all cache entries."""
        self.cache.put("key1", "value1")
        self.cache.put("key2", "value2")

        self.cache.clear()

        stats = self.cache.get_stats()
        assert stats["size"] == 0
        assert self.cache.get("key1") is None
        assert self.cache.get("key2") is None

    def test_cache_lru_ordering(self):
        """Test LRU ordering behavior."""
        # Fill cache to capacity
        for i in range(5):
            self.cache.put(f"key{i}", f"value{i}")

        # Access key0 to make it most recently used
        self.cache.get("key0")

        # Add new entry (should evict key1, not key0)
        self.cache.put("new_key", "new_value")

        assert self.cache.get("key0") == "value0"  # Still present
        assert self.cache.get("key1") is None  # Evicted
        assert self.cache.get("new_key") == "new_value"


class TestResponseCache:
    """Test ResponseCache functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.cache = ResponseCache(max_size=100, default_ttl=300.0)

    def test_cache_response_and_retrieve(self):
        """Test caching and retrieving responses."""
        message = "What is Python?"
        context = {"model": "gpt-5-mini", "system_message": "You are helpful"}
        response = "Python is a programming language."

        # Cache response
        self.cache.cache_response(message, context, response)

        # Retrieve cached response
        cached = self.cache.get_cached_response(message, context)
        assert cached == response

    def test_cache_key_normalization(self):
        """Test cache key normalization for similar messages."""
        context = {"model": "gpt-5-mini", "system_message": "Test"}
        response = "Test response"

        # Cache response with original message
        self.cache.cache_response("What is AI?", context, response)

        # Should hit cache with normalized message
        cached = self.cache.get_cached_response("what is ai?", context)
        assert cached == response

        # Should also hit with extra whitespace
        cached = self.cache.get_cached_response("  What is AI?  ", context)
        assert cached == response

    def test_should_not_cache_time_sensitive(self):
        """Test that time-sensitive responses are not cached."""
        context = {"model": "gpt-5-mini"}

        # Time-sensitive responses should not be cached
        time_sensitive_responses = [
            "The current time is 3:30 PM",
            "Today's news shows that...",
            "Right now, the market is...",
            "Latest breaking news...",
        ]

        for response in time_sensitive_responses:
            self.cache.cache_response("test message", context, response)
            # Should not be cached
            cached = self.cache.get_cached_response("test message", context)
            assert cached is None

    def test_should_not_cache_short_responses(self):
        """Test that very short responses are not cached."""
        context = {"model": "gpt-5-mini"}

        # Very short responses should not be cached
        short_responses = ["Yes.", "No", "OK", "   \n  "]

        for response in short_responses:
            self.cache.cache_response("test message", context, response)
            cached = self.cache.get_cached_response("test message", context)
            assert cached is None

    def test_cache_stats(self):
        """Test cache statistics."""
        # Perform some cache operations
        context = {"model": "test"}

        self.cache.cache_response("msg1", context, "Long response 1 for testing")
        self.cache.cache_response("msg2", context, "Long response 2 for testing")

        self.cache.get_cached_response("msg1", context)  # Hit
        self.cache.get_cached_response("msg3", context)  # Miss

        stats = self.cache.get_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1


class TestRequestDeduplicator:
    """Test RequestDeduplicator functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.deduplicator = RequestDeduplicator()

    @pytest.mark.asyncio
    async def test_deduplicate_identical_requests(self):
        """Test deduplication of identical requests."""
        call_count = 0

        async def mock_request():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate API delay
            return f"result_{call_count}"

        # Start multiple identical requests simultaneously
        tasks = []
        for _ in range(5):
            task = asyncio.create_task(
                self.deduplicator.deduplicate_request("test_key", mock_request)
            )
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)

        # Should have made only one actual API call
        assert call_count == 1

        # All results should be the same
        assert all(result == results[0] for result in results)
        assert results[0] == "result_1"

    @pytest.mark.asyncio
    async def test_different_requests_not_deduplicated(self):
        """Test that different requests are not deduplicated."""
        call_count = 0

        async def mock_request():
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        # Make requests with different keys
        result1 = await self.deduplicator.deduplicate_request("key1", mock_request)
        result2 = await self.deduplicator.deduplicate_request("key2", mock_request)

        # Should have made two separate API calls
        assert call_count == 2
        assert result1 == "result_1"
        assert result2 == "result_2"

    @pytest.mark.asyncio
    async def test_deduplicate_request_with_exception(self):
        """Test deduplication when request raises exception."""
        call_count = 0

        async def failing_request():
            nonlocal call_count
            call_count += 1
            raise ValueError("API error")

        # Start multiple identical requests that will fail
        with pytest.raises(ValueError, match="API error"):
            tasks = []
            for _ in range(3):
                task = asyncio.create_task(
                    self.deduplicator.deduplicate_request("fail_key", failing_request)
                )
                tasks.append(task)

            await asyncio.gather(*tasks)

        # Should have made multiple API calls since we don't deduplicate failures
        # (Each caller should get the chance to retry independently)
        assert call_count >= 1


class TestPerformanceMonitor:
    """Test PerformanceMonitor functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.monitor = PerformanceMonitor()

    def test_record_api_call_stats(self):
        """Test recording API call statistics."""
        # Record some API calls
        self.monitor.record_api_call(0.150, cache_hit=False)  # 150ms, cache miss
        self.monitor.record_api_call(0.080, cache_hit=True)  # 80ms, cache hit
        self.monitor.record_api_call(0.200, cache_hit=False)  # 200ms, cache miss

        stats = self.monitor.get_stats()

        assert stats["total_api_calls"] == 3
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 2
        assert stats["cache_hit_rate"] == pytest.approx(33.33, rel=0.1)
        assert stats["average_response_time_ms"] == pytest.approx(143.33, rel=0.1)

    def test_record_deduplication(self):
        """Test recording deduplication events."""
        self.monitor.record_deduplication()
        self.monitor.record_deduplication()

        stats = self.monitor.get_stats()
        assert stats["deduplicated_requests"] == 2

    def test_reset_stats(self):
        """Test resetting performance statistics."""
        # Record some data
        self.monitor.record_api_call(0.100)
        self.monitor.record_deduplication()

        # Reset
        self.monitor.reset_stats()

        stats = self.monitor.get_stats()
        assert stats["total_api_calls"] == 0
        assert stats["deduplicated_requests"] == 0
        assert stats["cache_hits"] == 0


class TestCachingDecorators:
    """Test caching decorators."""

    @pytest.mark.asyncio
    async def test_cached_response_decorator(self):
        """Test cached_response decorator."""
        call_count = 0

        @cached_response(ttl=300.0)
        async def test_function(message: str, gpt_model: str = "test"):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate processing
            return f"Response to: {message} (call #{call_count})"

        # First call should execute function
        result1 = await test_function("Hello", gpt_model="gpt-5-mini")
        assert call_count == 1
        assert "call #1" in result1

        # Second identical call should use cache
        result2 = await test_function("Hello", gpt_model="gpt-5-mini")
        assert call_count == 1  # No additional call
        assert result2 == result1

    @pytest.mark.asyncio
    async def test_deduplicated_request_decorator(self):
        """Test deduplicated_request decorator."""
        call_count = 0

        @deduplicated_request()
        async def test_function(message: str, model: str = "test"):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate API delay
            return f"Response {call_count}"

        # Start multiple simultaneous calls
        tasks = []
        for _ in range(5):
            task = asyncio.create_task(test_function("test message", model="gpt-5-mini"))
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Should have made only one actual call
        assert call_count == 1

        # All results should be identical
        assert all(result == results[0] for result in results)


class TestCacheIntegration:
    """Test cache integration and cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_caches(self):
        """Test cache cleanup functionality."""
        from src.caching import conversation_cache, response_cache

        # Add some entries that will expire quickly
        response_cache.cache.put("test1", "response1", ttl=0.1)
        response_cache.cache.put("test2", "response2", ttl=300.0)

        conversation_cache.put("conv1", "conversation1", ttl=0.1)
        conversation_cache.put("conv2", "conversation2", ttl=300.0)

        # Wait for short TTL entries to expire
        await asyncio.sleep(0.2)

        # Run cleanup
        expired_count = await cleanup_caches()

        # Should have cleaned up expired entries
        assert expired_count == 2

        # Verify expired entries are gone
        assert response_cache.cache.get("test1") is None
        assert response_cache.cache.get("test2") == "response2"
        assert conversation_cache.get("conv1") is None
        assert conversation_cache.get("conv2") == "conversation2"


if __name__ == "__main__":
    # Run caching tests with verbose output
    pytest.main([__file__, "-v"])
