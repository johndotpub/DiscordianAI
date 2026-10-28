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
import json
import logging
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Constants for caching
MIN_CACHABLE_RESPONSE_LENGTH = 10
RESPONSE_LENGTH_TTL_THRESHOLD = 1000
LONG_RESPONSE_TTL = 600.0
SHORT_RESPONSE_TTL = 300.0
POSITIONAL_CONFIG_INDEX = 3


def _extract_message_context(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[str, str, str]:
    """Extract message, model, and system message from decorated calls.

    Assumes positional argument 0 is the request-like object and positional
    argument 3 is the config-like object. If a decorated signature drifts,
    this helper falls back to keyword arguments and logs a warning.
    """
    request = args[0] if args and hasattr(args[0], "message") else kwargs.get("request")
    config = (
        args[POSITIONAL_CONFIG_INDEX]
        if len(args) > POSITIONAL_CONFIG_INDEX
        and hasattr(args[POSITIONAL_CONFIG_INDEX], "system_message")
        else kwargs.get("config")
    )

    if args and not hasattr(args[0], "message") and "request" not in kwargs:
        logger.warning(
            "Cached call signature drift: args[0] lacks message attribute for %s",
            type(args[0]).__name__,
        )

    if request and hasattr(request, "message"):
        message = request.message
    else:
        message = kwargs.get("message") or (args[0] if args and isinstance(args[0], str) else "")

    if config and hasattr(config, "system_message"):
        model = getattr(config, "model", "unknown")
        system_message = config.system_message
    else:
        model = kwargs.get("gpt_model") or kwargs.get("model", "unknown")
        system_message = kwargs.get("system_message", "")

    return message, model, system_message


def _extract_user_identity(user: Any) -> str | None:
    """Return a stable identity for a request owner, if one is available."""
    if user is None:
        return None

    if isinstance(user, dict):
        candidate = user.get("id")
    elif isinstance(user, (str, int)):
        candidate = user
    else:
        candidate = getattr(user, "id", None)

    if candidate is None:
        return None

    return str(candidate)


def _extract_conversation_summary(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Extract ordered conversation history from decorated calls."""
    if len(args) > 1 and isinstance(args[1], (list, tuple, dict)):
        return args[1]

    for key in ("conversation_summary", "conversation_history", "history"):
        if key in kwargs:
            return kwargs[key]

    return []


def _conversation_digest(conversation_summary: Any) -> str:
    """Hash ordered conversation history without losing message order."""
    if not conversation_summary:
        payload = "[]"
    else:
        try:
            payload = json.dumps(
                conversation_summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            payload = repr(conversation_summary)

    return hashlib.sha256(payload.encode()).hexdigest()


def _extract_request_scope(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Extract owner and conversation identity for cache and dedup keys."""
    request = args[0] if args and hasattr(args[0], "message") else kwargs.get("request")

    user = getattr(request, "user", None) if request is not None else None
    user_id = _extract_user_identity(user)
    conversation_key = getattr(request, "conversation_key", None) if request is not None else None

    if user_id is None and "user_id" in kwargs:
        user_id = _extract_user_identity(kwargs["user_id"])
    if user_id is None and "user" in kwargs:
        user_id = _extract_user_identity(kwargs["user"])
    if conversation_key is None and "conversation_key" in kwargs:
        conversation_key = kwargs["conversation_key"]

    conversation_summary = _extract_conversation_summary(args, kwargs)

    return {
        "user_id": user_id,
        "conversation_key": conversation_key,
        "conversation_digest": _conversation_digest(conversation_summary),
        "has_conversation": bool(conversation_summary),
    }


def _generate_scoped_key(message: str, context: dict[str, Any]) -> str | None:
    """Build a key scoped to the conversation (or legacy owner) and history."""
    user_id = context.get("user_id")
    conversation_key = context.get("conversation_key")
    conversation_digest = context.get("conversation_digest")
    has_conversation = bool(context.get("has_conversation"))

    if conversation_digest is None:
        conversation_summary = context.get("conversation_summary")
        if conversation_summary is None:
            conversation_summary = context.get("history", [])
        conversation_digest = _conversation_digest(conversation_summary)
        has_conversation = has_conversation or bool(conversation_summary)

    scope_id = conversation_key if conversation_key is not None else user_id
    if has_conversation and scope_id is None:
        return None

    normalized_message = str(message).strip().lower()

    context_key = {
        "model": context.get("model", "unknown"),
        "system_message_hash": hashlib.sha256(
            str(context.get("system_message") or "").encode(),
        ).hexdigest()[:8],
        "conversation_scope": "" if scope_id is None else str(scope_id),
        "conversation_digest": conversation_digest,
    }

    key_data = (normalized_message, context_key)
    return hashlib.sha256(str(key_data).encode()).hexdigest()


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

        if not response or len(response.strip()) < MIN_CACHABLE_RESPONSE_LENGTH:
            return False  # Don't cache very short responses

        # Don't cache time-sensitive responses
        response_lower = response.lower()
        time_indicators = [
            r"\bcurrent time\b",
            r"(?:^|[.!?]\s+)(?:today(?:'s)?|yesterday|tomorrow|latest|recent|tonight)\b",
            r"(?:^|[.!?]\s+)right now\b",
            r"(?:^|[.!?]\s+)just now\b",
            r"(?:^|[.!?]\s+)breaking news\b",
            r"\bthis (?:morning|afternoon|evening)\b",
        ]

        return not any(re.search(pattern, response_lower) for pattern in time_indicators)

    def _generate_cache_key(self, message: str, context: dict[str, Any]) -> str | None:
        """Generate cache key scoped to the request identity and context."""
        return _generate_scoped_key(message, context)

    def get_cached_response(self, message: str, context: dict[str, Any]) -> str | None:
        """Get cached response if available."""
        try:
            cache_key = self._generate_cache_key(message, context)
            if cache_key is None:
                return None

            cached_response = self.cache.get(cache_key)

            if cached_response:
                self.logger.debug("Cache hit for message: %s...", message[:50])
                return cached_response

        except Exception as e:  # noqa: BLE001
            self.logger.warning("Cache lookup failed: %s", e)
            return None
        else:
            return None

    def cache_response(
        self,
        message: str,
        context: dict[str, Any],
        response: str,
        ttl: float | None = None,
    ) -> None:
        """Cache response if appropriate."""
        try:
            if not self._should_cache_response(response):
                return

            cache_key = self._generate_cache_key(message, context)
            if cache_key is None:
                return

            # Use shorter TTL for potentially time-sensitive content
            if ttl is None:
                # Default TTL based on response characteristics
                if len(response) > RESPONSE_LENGTH_TTL_THRESHOLD:
                    ttl = LONG_RESPONSE_TTL
                else:
                    ttl = SHORT_RESPONSE_TTL

            self.cache.put(cache_key, response, ttl)
            self.logger.debug("Cached response for message: %s...", message[:50])

        except Exception as e:  # noqa: BLE001
            self.logger.warning("Cache storage failed: %s", e)

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
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    async def deduplicate_request(self, request_key: str, request_func: Callable) -> Any:
        """Execute request with deduplication.

        Args:
            request_key: Unique key identifying the request
            request_func: Async function to execute if not already pending

        Returns:
            Result from the request function
        """
        with self._lock:
            future = self._pending_requests.get(request_key)
            if future is not None:
                self.logger.debug("Deduplicating request: %s...", request_key[:20])
                is_leader = False
            else:
                future = asyncio.get_running_loop().create_future()
                self._pending_requests[request_key] = future
                is_leader = True

        if not is_leader:
            return await asyncio.shield(future)

        try:
            result = await request_func()
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise
        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        else:
            if not future.done():
                future.set_result(result)
            return result
        finally:
            with self._lock:
                if self._pending_requests.get(request_key) is future:
                    del self._pending_requests[request_key]


# Global cache instances
response_cache = ResponseCache(max_size=1000, default_ttl=300.0)
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

            message, model, system_message = _extract_message_context(args, kwargs)

            context = {
                "function": func_name,
                "model": model,
                "system_message": system_message,
                **_extract_request_scope(args, kwargs),
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
                message, model, system_message = _extract_message_context(args, kwargs)
                scope = _extract_request_scope(args, kwargs)
                scoped_key = _generate_scoped_key(
                    message,
                    {
                        "model": model,
                        "system_message": system_message,
                        **scope,
                    },
                )
                if scoped_key is None:
                    return await func(*args, **kwargs)

                request_key = f"{func.__name__}:{scoped_key}"

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


async def cleanup_caches():
    """Clean up expired cache entries."""
    try:
        response_expired = response_cache.cleanup()

        if response_expired > 0:
            logger.info("Cleaned up %d expired response cache entries", response_expired)

    except Exception:
        logger.exception("Cache cleanup failed")
        return 0
    else:
        return response_expired


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
    logger.info("Starting cache cleanup background task")

    while True:
        await _cache_cleanup_tick(interval, logger)
