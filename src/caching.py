"""Performance optimization utilities including caching and connection pooling.

This module provides:
- Response caching for repeated queries
- LRU cache for conversation contexts
- Request deduplication for identical API calls
- Connection pooling optimizations
- Performance monitoring and metrics
"""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
import hashlib
import logging
import threading
import time
from typing import Any


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    value: Any
    timestamp: float
    access_count: int = 0
    ttl: float = 300.0  # 5 minutes default

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.timestamp > self.ttl

    def touch(self):
        """Update access count and timestamp."""
        self.access_count += 1


class ThreadSafeLRUCache:
    """Thread-safe LRU cache implementation with TTL support.

    Provides fast caching with automatic cleanup of expired entries.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        """Initialize cache with capacity and default TTL.

        Args:
            max_size: Maximum number of entries to store.
            default_ttl: Default time-to-live per entry in seconds.
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expired": 0,
        }

    def _make_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments."""
        # Create a deterministic key from arguments
        key_data = str((args, sorted(kwargs.items())))
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None

            entry = self._cache[key]

            # Check if expired
            if entry.is_expired():
                del self._cache[key]
                self._stats["expired"] += 1
                self._stats["misses"] += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.touch()
            self._stats["hits"] += 1

            return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store value in cache."""
        with self._lock:
            if ttl is None:
                ttl = self.default_ttl

            # Remove existing entry if present
            if key in self._cache:
                del self._cache[key]

            # Add new entry
            entry = CacheEntry(value=value, timestamp=time.time(), ttl=ttl)
            self._cache[key] = entry

            # Enforce max size
            while len(self._cache) > self.max_size:
                # Remove least recently used
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats["evictions"] += 1

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]

            for key in expired_keys:
                del self._cache[key]

            self._stats["expired"] += len(expired_keys)
            return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hit_rate": round(hit_rate, 2),
                "total_requests": total_requests,
                **self._stats,
            }


class ResponseCache:
    """High-level response caching for API calls.

    Caches expensive API responses with intelligent cache key generation.
    """

    def __init__(self, max_size: int = 500, default_ttl: float = 300.0):
        """Initialize response cache wrapper.

        Args:
            max_size: Maximum cache entries to store.
            default_ttl: Default TTL for cached responses (seconds).
        """
        self.cache = ThreadSafeLRUCache(max_size, default_ttl)
        self.logger = logging.getLogger(__name__)

    def _should_cache_response(self, response: str, error: Exception | None = None) -> bool:
        """Determine if response should be cached."""
        if error:
            return False  # Don't cache errors

        if not response or len(response.strip()) < 10:
            return False  # Don't cache very short responses

        # Don't cache time-sensitive responses
        time_indicators = [
            "current time",
            "right now",
            "today",
            "yesterday",
            "tomorrow",
            "this morning",
            "this afternoon",
            "this evening",
            "tonight",
            "latest",
            "recent",
            "just now",
            "breaking news",
        ]

        response_lower = response.lower()
        return not any(indicator in response_lower for indicator in time_indicators)

    def _generate_cache_key(self, message: str, context: dict[str, Any]) -> str:
        """Generate cache key for message and context."""
        # Normalize message for better cache hits
        normalized_message = message.strip().lower()

        # Include relevant context in key
        context_key = {
            "model": context.get("model", "unknown"),
            "system_message_hash": hashlib.sha256(
                context.get("system_message", "").encode()
            ).hexdigest()[:8],
            # Don't include conversation history in key for broader cache hits
        }

        key_data = (normalized_message, context_key)
        return hashlib.sha256(str(key_data).encode()).hexdigest()

    def get_cached_response(self, message: str, context: dict[str, Any]) -> str | None:
        """Get cached response if available."""
        try:
            cache_key = self._generate_cache_key(message, context)
            cached_response = self.cache.get(cache_key)

            if cached_response:
                self.logger.debug(f"Cache hit for message: {message[:50]}...")
                return cached_response

        except Exception as e:  # noqa: BLE001 - cache lookup should never crash callers
            self.logger.warning(f"Cache lookup failed: {e}")
            return None
        else:
            return None

    def cache_response(
        self, message: str, context: dict[str, Any], response: str, ttl: float | None = None
    ) -> None:
        """Cache response if appropriate."""
        try:
            if not self._should_cache_response(response):
                return

            cache_key = self._generate_cache_key(message, context)

            # Use shorter TTL for potentially time-sensitive content
            if ttl is None:
                # Default TTL based on response characteristics
                ttl = 600.0 if len(response) > 1000 else 300.0

            self.cache.put(cache_key, response, ttl)
            self.logger.debug(f"Cached response for message: {message[:50]}...")

        except Exception as e:  # noqa: BLE001 - cache failures should not raise
            self.logger.warning(f"Cache storage failed: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self.cache.get_stats()

    def cleanup(self) -> int:
        """Clean up expired entries."""
        return self.cache.cleanup_expired()


class RequestDeduplicator:
    """Deduplicates identical API requests to prevent redundant calls.

    If multiple identical requests are made simultaneously, only one
    actual API call is made and the result is shared.
    """

    def __init__(self):
        """Initialize deduplicator state and locks."""
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def deduplicate_request(self, request_key: str, request_func: Callable) -> Any:
        """Execute request with deduplication.

        Args:
            request_key: Unique key identifying the request
            request_func: Async function to execute if not already pending

        Returns:
            Result from the request function
        """
        async with self._lock:
            # Check if request is already pending
            if request_key in self._pending_requests:
                self.logger.debug(f"Deduplicating request: {request_key[:20]}...")
                future = self._pending_requests[request_key]
                # Wait for the existing request to complete
                return await future

            # Create new future for this request
            future = asyncio.Future()
            self._pending_requests[request_key] = future

        try:
            # Execute the request
            result = await request_func()
        except Exception as e:
            future.set_exception(e)
            raise
        else:
            future.set_result(result)
            return result

        finally:
            # Clean up the pending request
            async with self._lock:
                if request_key in self._pending_requests:
                    del self._pending_requests[request_key]


# Global cache instances
response_cache = ResponseCache(max_size=1000, default_ttl=300.0)
conversation_cache = ThreadSafeLRUCache(max_size=500, default_ttl=1800.0)  # 30 minutes
request_deduplicator = RequestDeduplicator()


def cached_response(ttl: float = 300.0, cache_instance: ResponseCache | None = None):
    """Decorator to cache function responses.

    Args:
        ttl: Time to live in seconds
        cache_instance: Custom cache instance to use
    """

    def decorator(func: Callable) -> Callable:
        cache = cache_instance or response_cache

        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate cache key from function name and arguments
            func_name = func.__name__
            message = kwargs.get("message") or (args[0] if args else "")

            context = {
                "function": func_name,
                "model": kwargs.get("gpt_model") or kwargs.get("model", "unknown"),
                "system_message": kwargs.get("system_message", ""),
            }

            # Try to get cached response
            if isinstance(message, str) and message:
                cached = cache.get_cached_response(message, context)
                if cached is not None:
                    return cached

            # Execute function and cache result
            result = await func(*args, **kwargs)

            # Cache successful responses
            if isinstance(result, str) and isinstance(message, str):
                cache.cache_response(message, context, result, ttl)

            return result

        return wrapper

    return decorator


def deduplicated_request(key_func: Callable | None = None):
    """Decorator to deduplicate identical requests.

    Args:
        key_func: Function to generate request key from arguments
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate request key
            if key_func:
                request_key = key_func(*args, **kwargs)
            else:
                # Default key generation
                message = kwargs.get("message") or (args[0] if args else "")
                model = kwargs.get("gpt_model") or kwargs.get("model", "unknown")
                request_key = f"{func.__name__}:{model}:{hash(str(message))}"

            # Execute with deduplication
            async def request_func():
                return await func(*args, **kwargs)

            return await request_deduplicator.deduplicate_request(request_key, request_func)

        return wrapper

    return decorator


class PerformanceMonitor:
    """Monitor and report performance metrics."""

    def __init__(self):
        """Initialize metrics and synchronization primitives."""
        self.metrics = {
            "api_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_response_time": 0.0,
            "deduplicated_requests": 0,
        }
        self._lock = threading.Lock()

    def record_api_call(self, response_time: float, cache_hit: bool = False):
        """Record API call metrics."""
        with self._lock:
            self.metrics["api_calls"] += 1
            self.metrics["total_response_time"] += response_time

            if cache_hit:
                self.metrics["cache_hits"] += 1
            else:
                self.metrics["cache_misses"] += 1

    def record_deduplication(self):
        """Record request deduplication event."""
        with self._lock:
            self.metrics["deduplicated_requests"] += 1

    def get_stats(self) -> dict[str, Any]:
        """Get performance statistics."""
        with self._lock:
            total_requests = self.metrics["api_calls"]
            avg_response_time = (
                self.metrics["total_response_time"] / total_requests if total_requests > 0 else 0
            )

            cache_hit_rate = (
                self.metrics["cache_hits"]
                / (self.metrics["cache_hits"] + self.metrics["cache_misses"])
                * 100
                if (self.metrics["cache_hits"] + self.metrics["cache_misses"]) > 0
                else 0
            )

            return {
                "total_api_calls": total_requests,
                "average_response_time_ms": round(avg_response_time * 1000, 2),
                "cache_hit_rate": round(cache_hit_rate, 2),
                "deduplicated_requests": self.metrics["deduplicated_requests"],
                **self.metrics,
            }

    def reset_stats(self):
        """Reset all performance statistics."""
        with self._lock:
            self.metrics = {
                "api_calls": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "total_response_time": 0.0,
                "deduplicated_requests": 0,
            }


# Global performance monitor
performance_monitor = PerformanceMonitor()


async def cleanup_caches():
    """Clean up expired cache entries."""
    try:
        response_expired = response_cache.cleanup()
        conversation_expired = conversation_cache.cleanup_expired()

        if response_expired > 0 or conversation_expired > 0:
            logger = logging.getLogger(__name__)
            logger.info(f"Cleaned up {response_expired} expired response cache entries")
            logger.info(f"Cleaned up {conversation_expired} expired conversation cache entries")

        return response_expired + conversation_expired

    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception("Cache cleanup failed")
        return 0


async def _cache_cleanup_tick(interval: int, logger: logging.Logger) -> None:
    """Execute a single cleanup tick with error handling."""
    try:
        await asyncio.sleep(interval)
        await cleanup_caches()
    except asyncio.CancelledError:
        logger.info("Cache cleanup task cancelled")
        raise
    except Exception:
        logger.exception("Error in cache cleanup task")
        await asyncio.sleep(60)  # Wait 1 minute before retrying


# Background cache cleanup task
async def start_cache_cleanup_task(interval: int = 300):  # 5 minutes
    """Start background cache cleanup task."""
    logger = logging.getLogger(__name__)
    logger.info("Starting cache cleanup background task")

    while True:
        await _cache_cleanup_tick(interval, logger)
