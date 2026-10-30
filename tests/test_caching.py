"""Tests for the caching and performance optimization system.

This test suite covers:
- ThreadSafeLRUCache functionality
- ResponseCache behavior and key generation
- Request deduplication logic
- Cache decorators and integration
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from src.caching import (
    CacheEntry,
    RequestDeduplicator,
    ResponseCache,
    ThreadSafeLRUCache,
    cached_response,
    deduplicated_request,
)


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_cache_entry_creation(self):
        """Test creating a cache entry."""
        entry = CacheEntry(value="test response", timestamp=time.time(), ttl=300.0)

        assert entry.value == "test response"
        assert not entry.is_expired()

    def test_cache_entry_expiration(self):
        """Test cache entry expiration."""
        # Create expired entry
        old_timestamp = time.time() - 400  # 400 seconds ago
        entry = CacheEntry(
            value="expired response",
            timestamp=old_timestamp,
            ttl=300.0,  # 300 second TTL
        )

        assert entry.is_expired()


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
        with patch("src.caching.time.time", side_effect=[100.0, 100.0, 100.25]):
            # Put entry with short TTL
            self.cache.put("expire_key", "expire_value", ttl=0.1)

            # Should be available immediately
            assert self.cache.get("expire_key") == "expire_value"

            # Should be expired now
            assert self.cache.get("expire_key") is None

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

    def test_cache_key_normalization_strips_whitespace_only(self):
        """Cache keys ignore surrounding whitespace but preserve letter case."""
        context = {"model": "gpt-5-mini", "system_message": "Test"}
        response = "Test response"

        # Cache response with original message
        self.cache.cache_response("What is AI?", context, response)

        # Whitespace is not part of the prompt
        cached = self.cache.get_cached_response("  What is AI?  ", context)
        assert cached == response

        # Case is meaningful, so a differently-cased prompt is a cache miss
        cached = self.cache.get_cached_response("what is ai?", context)
        assert cached is None

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
                self.deduplicator.deduplicate_request("test_key", mock_request),
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
            await asyncio.sleep(0)
            msg = "API error"
            raise ValueError(msg)

        # Followers wait on the leader's future, so the failure is shared.
        tasks = [
            asyncio.create_task(
                self.deduplicator.deduplicate_request("fail_key", failing_request),
            )
            for _ in range(3)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # One call fails once; every follower receives that same exception.
        assert call_count == 1
        assert all(isinstance(result, ValueError) for result in results)
        assert all(result is results[0] for result in results)
        assert str(results[0]) == "API error"


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


if __name__ == "__main__":
    # Run caching tests with verbose output
    pytest.main([__file__, "-v"])
