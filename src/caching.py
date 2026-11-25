"""Performance optimization utilities including caching and connection pooling.

This module provides:
- Response caching for repeated queries
- LRU cache for conversation contexts
- Request deduplication for identical API calls
- Connection pooling optimizations
"""

import asyncio
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

from cachetools import TLRUCache

from .config import DEFAULT_CACHE_TTL
from .providers.base import object_field

logger = logging.getLogger(__name__)

# Constants for caching
MIN_CACHABLE_RESPONSE_LENGTH = 10
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


def _image_digests(request: Any) -> list[str]:
    """Return short content digests for images attached to a request."""
    images = getattr(request, "images", ()) if request is not None else ()
    digests: list[str] = []
    for image in images or ():
        payload = getattr(image, "data_b64", "") or ""
        digests.append(hashlib.sha256(str(payload).encode()).hexdigest()[:16])
    return digests


def _extract_conversation_summary(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Extract ordered conversation history from decorated calls."""
    if len(args) > 1 and isinstance(args[1], (list, tuple, dict)):
        return args[1]

    for key in ("conversation_summary", "conversation_history", "history"):
        if key in kwargs:
            return kwargs[key]

    return []


def conversation_digest(conversation_summary: Any) -> str:
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
        "conversation_digest": conversation_digest(conversation_summary),
        "has_conversation": bool(conversation_summary),
        "image_digests": _image_digests(request),
    }


def _generate_scoped_key(message: str, context: dict[str, Any], *, salt: str) -> str | None:
    """Build a key scoped to the conversation, history, and routing decision."""
    user_id = context.get("user_id")
    conversation_key = context.get("conversation_key")
    digest = context.get("conversation_digest")

    if digest is None:
        conversation_summary = context.get("conversation_summary")
        if conversation_summary is None:
            conversation_summary = context.get("history", [])
        digest = conversation_digest(conversation_summary)

    scope_id = conversation_key if conversation_key is not None else user_id
    if scope_id is None:
        return None

    normalized_message = str(message).strip()

    context_key = {
        "model": context.get("model", "unknown"),
        "system_message_hash": hashlib.sha256(
            str(context.get("system_message") or "").encode(),
        ).hexdigest()[:8],
        "conversation_scope": str(scope_id),
        "conversation_digest": digest,
        "service": context.get("service", "unknown"),
        "router_id": context.get("router_id", "unknown"),
        "policy_version": context.get("policy_version", "unknown"),
        "decision_source": context.get("decision_source", "unknown"),
        "function": context.get("function", "unknown"),
        "route": context.get("route", ""),
        "degraded": bool(context.get("degraded", False)),
        "image_digests": list(context.get("image_digests") or []),
        "salt": salt,
    }

    key_data = (normalized_message, context_key)
    return hashlib.sha256(str(key_data).encode()).hexdigest()


def _extract_routing_context(request: Any, func_name: str) -> dict[str, Any]:
    """Return routing fields for a cache key, with explicit legacy defaults."""
    routing = getattr(request, "routing", None) if request is not None else None

    def read(name: str, default: Any) -> Any:
        return default if routing is None else object_field(routing, name, default)

    salt = read("salt", None)
    if not isinstance(salt, str) or not salt:
        salt = f"{func_name}:unrouted"
    return {
        "service": read("service", "unknown"),
        "router_id": read("router_id", "unknown"),
        "policy_version": read("policy_version", "unknown"),
        "decision_source": read("decision_source", "unknown"),
        "route": read("route", ""),
        "degraded": bool(read("degraded", False)),
        "cacheable": bool(read("cacheable", True)),
        "salt": salt,
    }


def _cache_context(
    func_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[Any, dict[str, Any], str]:
    """Build the cache context and required salt for one decorated call."""
    message, model, system_message = _extract_message_context(args, kwargs)
    request = args[0] if args and hasattr(args[0], "message") else kwargs.get("request")
    routing = _extract_routing_context(request, func_name)
    salt = routing.pop("salt")
    context = {
        "function": func_name,
        "model": model,
        "system_message": system_message,
        **_extract_request_scope(args, kwargs),
        **routing,
    }
    return message, context, salt


@dataclass(frozen=True)
class _CacheEntry:
    """Value and time-to-live stored in the response cache."""

    value: Any
    ttl: float


class _StatsTLRUCache(TLRUCache):
    """TLRUCache that counts the entries it evicts and expires."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.evicted = 0
        self.expired = 0

    def popitem(self) -> tuple[str, _CacheEntry]:
        self.evicted += 1
        return super().popitem()

    def expire(self, time: float | None = None) -> list[tuple[str, _CacheEntry]]:
        expired = super().expire(time)
        self.expired += len(expired)
        return expired


class ThreadSafeLRUCache:
    """Thread-safe LRU cache implementation with TTL support.

    Provides fast caching with automatic cleanup of expired entries.
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = DEFAULT_CACHE_TTL,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize cache with capacity and default TTL.

        Args:
            max_size: Maximum number of entries to store.
            default_ttl: Default time-to-live per entry in seconds.
            clock: Optional time source used for TTL calculations.
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._clock = clock or time.time
        self._cache: _StatsTLRUCache[str, _CacheEntry] = _StatsTLRUCache(
            max_size,
            ttu=lambda _key, entry, now: now + entry.ttl,
            timer=self._clock,
        )
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
            try:
                entry = self._cache[key]
            except KeyError:
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store value in cache."""
        with self._lock:
            if ttl is None:
                ttl = self.default_ttl

            self._cache[key] = _CacheEntry(value=value, ttl=ttl)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            size = len(self._cache)
            self._stats["evictions"] = self._cache.evicted
            self._stats["expired"] = self._cache.expired
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0

            return {
                "size": size,
                "max_size": self.max_size,
                "hit_rate": round(hit_rate, 2),
                "total_requests": total_requests,
                **self._stats,
            }


class ResponseCache:
    """High-level response caching for API calls.

    Caches expensive API responses with intelligent cache key generation.
    """

    def __init__(
        self,
        max_size: int = 500,
        default_ttl: float = DEFAULT_CACHE_TTL,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize response cache wrapper.

        Args:
            max_size: Maximum cache entries to store.
            default_ttl: Default TTL for cached responses (seconds).
            clock: Optional time source used for TTL calculations.
        """
        self.cache = ThreadSafeLRUCache(max_size, default_ttl, clock)
        self.logger = logging.getLogger(__name__)

    def _should_cache_response(self, response: str, error: Exception | None = None) -> bool:
        """Determine if response should be cached."""
        if error:
            return False  # Don't cache errors

        if getattr(response, "truncated", False):
            return False  # A partial answer must not be replayed as the answer

        if not response or len(response.strip()) < MIN_CACHABLE_RESPONSE_LENGTH:
            return False  # Don't cache very short responses

        # Don't cache time-sensitive responses
        response_lower = response.lower()
        time_indicators = [
            r"\bcurrent time\b",
            r"\b(?:today(?:'s)?|yesterday|tomorrow|latest|recent|tonight)\b",
            r"\bright now\b",
            r"\bjust now\b",
            r"\bbreaking news\b",
            r"\bthis (?:morning|afternoon|evening)\b",
        ]

        return not any(re.search(pattern, response_lower) for pattern in time_indicators)

    def _generate_cache_key(
        self,
        message: str,
        context: dict[str, Any],
        *,
        salt: str,
    ) -> str | None:
        """Generate cache key scoped to the request identity and routing decision."""
        return _generate_scoped_key(message, context, salt=salt)

    def get_cached_response(
        self,
        message: str,
        context: dict[str, Any],
        *,
        salt: str,
    ) -> str | None:
        """Get cached response if available."""
        try:
            if context.get("cacheable", True) is False:
                return None

            cache_key = self._generate_cache_key(message, context, salt=salt)
            if cache_key is None:
                return None

            cached_response = self.cache.get(cache_key)

            if cached_response:
                self.logger.debug("Cache hit for message (length=%d)", len(message))
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
        *,
        salt: str,
    ) -> None:
        """Cache response if appropriate."""
        try:
            if context.get("cacheable", True) is False:
                return
            if not self._should_cache_response(response):
                return

            cache_key = self._generate_cache_key(message, context, salt=salt)
            if cache_key is None:
                return

            self.cache.put(cache_key, response, ttl)
            self.logger.debug("Cached response for message (length=%d)", len(message))

        except Exception as e:  # noqa: BLE001
            self.logger.warning("Cache storage failed: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self.cache.get_stats()


class _LeaderFailed(Exception):  # noqa: N818 - the sentinel name is intentional
    """Signal that the shared request failed and followers must run independently."""


def _consume_future_exception(future: asyncio.Future) -> None:
    """Retrieve an unobserved shared-future exception to avoid asyncio warnings."""
    if not future.cancelled():
        future.exception()


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
            try:
                return await asyncio.shield(future)
            except _LeaderFailed:
                return await request_func()

        try:
            result = await request_func()
        except asyncio.CancelledError:
            self._fail_shared_future(future)
            raise
        except Exception:
            self._fail_shared_future(future)
            raise
        else:
            if not future.done():
                future.set_result(result)
            return result
        finally:
            with self._lock:
                if self._pending_requests.get(request_key) is future:
                    del self._pending_requests[request_key]

    @staticmethod
    def _fail_shared_future(future: asyncio.Future) -> None:
        """Wake followers with the sentinel and consume the unawaited exception."""
        if future.done():
            return
        future.set_exception(_LeaderFailed("shared request did not produce a result"))
        future.add_done_callback(_consume_future_exception)


# Global cache instances
response_cache = ResponseCache(max_size=2000, default_ttl=DEFAULT_CACHE_TTL)
request_deduplicator = RequestDeduplicator()


def cached_response(
    ttl: float = DEFAULT_CACHE_TTL,
    cache_instance: ResponseCache | None = None,
    *,
    key_fn: Callable[..., str | None] | None = None,
    result_text: Callable[[Any], str | None] | None = None,
):
    """Decorator to cache function responses.

    Args:
        ttl: Time to live in seconds.
        cache_instance: Custom cache instance to use.
        key_fn: Optional explicit key builder. When provided, the returned key
            is used directly and an eligible non-``None`` result is cached. When
            absent, the original positional message/config extraction and
            scoping rules apply unchanged.
        result_text: Optional extractor for the answer text inside a structured
            result. When provided with ``key_fn``, the extracted text must pass
            the same eligibility gate as ``ResponseCache.cache_response``.
    """

    def decorator(func: Callable) -> Callable:
        cache = cache_instance or response_cache

        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if key_fn is not None:
                cache_key = key_fn(*args, **kwargs)
                if cache_key is None:
                    return await func(*args, **kwargs)

                cached = cache.cache.get(cache_key)
                if cached is not None:
                    return cached

                result = await func(*args, **kwargs)
                if result is not None:
                    text: str | None
                    if result_text is not None:
                        text = result_text(result)
                    elif isinstance(result, str):
                        text = result
                    else:
                        text = None

                    is_cacheable = cache._should_cache_response  # noqa: SLF001 - cache policy
                    if text and is_cacheable(text):
                        cache.cache.put(cache_key, result, ttl)
                    else:
                        cache.logger.debug(
                            "Skipping cache write for %s: result is not cacheable",
                            func.__name__,
                        )
                return result

            # Generate cache key from function name, arguments, and routing.
            func_name = func.__name__
            message, context, salt = _cache_context(func_name, args, kwargs)

            # Try to get cached response
            if isinstance(message, str) and message:
                cached = cache.get_cached_response(message, context, salt=salt)
                if cached is not None:
                    return cached

            # Execute function and cache result
            result = await func(*args, **kwargs)

            # Cache successful responses
            if isinstance(result, str) and isinstance(message, str):
                cache.cache_response(message, context, result, ttl, salt=salt)

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
                # Default key generation uses the same routing fields as the cache.
                message, context, salt = _cache_context(func.__name__, args, kwargs)
                scoped_key = _generate_scoped_key(message, context, salt=salt)
                if scoped_key is None:
                    return await func(*args, **kwargs)

                request_key = f"{func.__name__}:{scoped_key}"

            # Execute with deduplication
            async def request_func():
                return await func(*args, **kwargs)

            return await request_deduplicator.deduplicate_request(request_key, request_func)

        return wrapper

    return decorator
