"""Regression tests for cache and deduplication request scoping."""

import asyncio
import logging
import time
from types import SimpleNamespace

import pytest

from src.caching import RequestDeduplicator, ResponseCache, cached_response, response_cache
from src.models import AIRequest, OpenAIConfig
from src.openai_processing import _fetch_openai_response


class FakeCompletions:
    def __init__(self, calls, delay=0.0):
        self.calls = calls
        self.delay = delay

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        history = kwargs["messages"][1:-1]
        history_text = " | ".join(item["content"] for item in history) or "no history"
        content = f"Reply to {history_text}: {kwargs['messages'][-1]['content']}"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ]
        )


class FakeOpenAIClient:
    def __init__(self, delay=0.0):
        self.calls = []
        self.chat = SimpleNamespace(completions=FakeCompletions(self.calls, delay))


@pytest.fixture(autouse=True)
def clear_response_cache():
    response_cache.cache.clear()
    yield
    response_cache.cache.clear()


def make_request(message, user_id):
    return AIRequest(
        message=message,
        user=SimpleNamespace(id=user_id),
        conversation_manager=SimpleNamespace(),
        logger=logging.getLogger("test_caching_scope"),
    )


CONFIG = OpenAIConfig(model="gpt-test", system_message="You are a test assistant.")


@pytest.mark.asyncio
async def test_different_users_same_message_different_history_are_isolated():
    client = FakeOpenAIClient()
    history_a = [{"role": "user", "content": "private fact from user A"}]
    history_b = [{"role": "user", "content": "private fact from user B"}]

    response_a = await _fetch_openai_response(
        make_request("same question", 1), history_a, client, CONFIG
    )
    response_b = await _fetch_openai_response(
        make_request("same question", 2), history_b, client, CONFIG
    )

    assert len(client.calls) == 2
    assert response_b != response_a
    assert "private fact from user A" not in response_b


@pytest.mark.asyncio
async def test_same_user_same_message_different_history_are_isolated():
    client = FakeOpenAIClient()
    first_history = [{"role": "user", "content": "earlier context one"}]
    second_history = [{"role": "user", "content": "earlier context two"}]

    first = await _fetch_openai_response(
        make_request("same question", 7), first_history, client, CONFIG
    )
    second = await _fetch_openai_response(
        make_request("same question", 7), second_history, client, CONFIG
    )

    assert len(client.calls) == 2
    assert first != second


@pytest.mark.asyncio
async def test_concurrent_identical_requests_share_one_api_call():
    client = FakeOpenAIClient(delay=0.1)
    history = [{"role": "user", "content": "shared context"}]

    first, second = await asyncio.gather(
        _fetch_openai_response(make_request("same question", 3), history, client, CONFIG),
        _fetch_openai_response(make_request("same question", 3), history, client, CONFIG),
    )

    assert len(client.calls) == 1
    assert first == second


@pytest.mark.asyncio
async def test_different_identities_run_in_parallel():
    delay = 0.4
    client = FakeOpenAIClient(delay=delay)
    history = [{"role": "user", "content": "shared context"}]

    started = time.monotonic()
    await asyncio.gather(
        _fetch_openai_response(make_request("same question", 11), history, client, CONFIG),
        _fetch_openai_response(make_request("same question", 22), history, client, CONFIG),
    )
    elapsed = time.monotonic() - started

    assert len(client.calls) == 2
    assert elapsed < delay * 1.5
    assert elapsed < (delay * 2) * 0.75


@pytest.mark.asyncio
async def test_cancelled_leader_does_not_deadlock_later_requests():
    deduplicator = RequestDeduplicator()
    leader_started = asyncio.Event()

    async def leader_work():
        leader_started.set()
        await asyncio.sleep(10)
        return "leader"

    async def follower_work():
        return "follower"

    async def unrelated_work():
        return "unrelated"

    leader = asyncio.create_task(deduplicator.deduplicate_request("shared", leader_work))
    await asyncio.wait_for(leader_started.wait(), timeout=1.0)
    follower = asyncio.create_task(deduplicator.deduplicate_request("shared", follower_work))
    await asyncio.sleep(0.05)

    leader.cancel()
    try:
        result = await asyncio.wait_for(
            deduplicator.deduplicate_request("unrelated", unrelated_work),
            timeout=1.0,
        )
        assert result == "unrelated"
    finally:
        follower.cancel()
        await asyncio.gather(leader, follower, return_exceptions=True)


@pytest.mark.asyncio
async def test_stateless_repeat_still_hits_cache():
    client = FakeOpenAIClient()
    request = make_request("stateless question", 5)

    first = await _fetch_openai_response(request, [], client, CONFIG)
    second = await _fetch_openai_response(request, [], client, CONFIG)

    assert len(client.calls) == 1
    assert first == second


def test_cache_keys_preserve_case_and_ignore_surrounding_whitespace():
    cache = ResponseCache()
    context = {"model": "gpt-test", "system_message": "test"}

    salt = "local:heuristic@1:1"
    assert cache._generate_cache_key("ABC", context, salt=salt) != cache._generate_cache_key(
        "abc", context, salt=salt
    )
    assert cache._generate_cache_key("ABC", context, salt=salt) == cache._generate_cache_key(
        "ABC", context, salt=salt
    )
    assert cache._generate_cache_key(" ABC ", context, salt=salt) == cache._generate_cache_key(
        "ABC", context, salt=salt
    )


@pytest.mark.asyncio
async def test_cached_response_for_uppercase_prompt_is_not_served_for_lowercase():
    calls = []

    @cached_response(ttl=300.0)
    async def answer(message):
        calls.append(message)
        return f"answer for {message}"

    uppercase = await answer("ABC")
    lowercase = await answer("abc")
    repeated_uppercase = await answer("ABC")

    assert uppercase == "answer for ABC"
    assert lowercase == "answer for abc"
    assert repeated_uppercase == "answer for ABC"
    assert calls == ["ABC", "abc"]


def test_bounded_size_eviction_still_holds():
    cache = ResponseCache(max_size=2, default_ttl=300.0)
    context = {"model": "gpt-test", "system_message": "test"}

    salt = "local:heuristic@1:1"
    cache.cache_response("first message", context, "First sufficiently long response", salt=salt)
    cache.cache_response("second message", context, "Second sufficiently long response", salt=salt)
    cache.cache_response("third message", context, "Third sufficiently long response", salt=salt)

    stats = cache.get_stats()
    assert stats["size"] == 2
    assert stats["evictions"] == 1
    assert cache.get_cached_response("first message", context, salt=salt) is None
    assert cache.get_cached_response("third message", context, salt=salt) is not None
