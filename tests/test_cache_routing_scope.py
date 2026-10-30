"""Cache keys carry the routing decision, not just the prompt and history."""

import logging

import pytest

from src.caching import ResponseCache, _generate_scoped_key, cached_response
from src.models import AIRequest, RoutingMetadata
from src.routing.contracts import RouterConfig
from src.routing.features import Cue
from src.routing.scoring import decide

SALT = "local:heuristic@1:1"


def _context(**overrides):
    context = {
        "model": "gpt-test",
        "system_message": "system",
        "conversation_scope": "dm:1",
        "conversation_digest": "digest",
        "service": "openai",
        "router_id": "heuristic@1",
        "policy_version": "1",
        "decision_source": "structural",
        "function": "_fetch_openai_response",
        "route": "local",
        "degraded": False,
    }
    context.update(overrides)
    return context


def test_scoped_key_requires_an_explicit_salt():
    with pytest.raises(TypeError):
        _generate_scoped_key("question", _context())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", "perplexity"),
        ("router_id", "clef@abc"),
        ("policy_version", "2"),
        ("decision_source", "override"),
        ("function", "another_function"),
        ("route", "web"),
        ("degraded", True),
    ],
)
def test_scoped_key_changes_with_every_routing_field(field, value):
    base = _generate_scoped_key("question", _context(), salt=SALT)
    changed = _generate_scoped_key("question", _context(**{field: value}), salt=SALT)

    assert changed != base


def test_scoped_key_changes_with_the_salt():
    local = _generate_scoped_key("question", _context(route="local"), salt="local:h:1")
    web = _generate_scoped_key("question", _context(route="web"), salt="web:h:1")

    assert local != web


def test_web_answer_is_never_served_for_a_local_route_and_vice_versa():
    cache = ResponseCache()
    local = _context()
    web = _context(service="perplexity", route="web", salt="web:heuristic@1:1")
    local_salt = "local:heuristic@1:1"
    web_salt = "web:heuristic@1:1"
    answer = "A sufficiently long answer to be cacheable."

    cache.cache_response("same question", local, answer, salt=local_salt)

    assert cache.get_cached_response("same question", local, salt=local_salt) == answer
    assert cache.get_cached_response("same question", web, salt=web_salt) is None


def test_a_degraded_fallback_does_not_satisfy_a_successful_route():
    cache = ResponseCache()
    healthy = _context(service="perplexity", route="web")
    degraded = _context(service="openai", route="web", degraded=True)
    healthy_salt = "web:heuristic@1:1"
    degraded_salt = "web:heuristic@1:1"
    answer = "A sufficiently long degraded local answer."

    cache.cache_response("same question", degraded, answer, salt=degraded_salt)

    assert cache.get_cached_response("same question", degraded, salt=degraded_salt) == answer
    assert cache.get_cached_response("same question", healthy, salt=healthy_salt) is None


def test_cache_response_refuses_when_the_decision_is_not_cacheable():
    cache = ResponseCache()
    context = _context(cacheable=False)

    cache.cache_response("question", context, "A long enough answer to cache.", salt=SALT)

    assert cache.get_cached_response("question", context, salt=SALT) is None


def test_unsure_decision_is_not_cached():
    cue = Cue(
        signal="pred.status",
        klass="bearing",
        span=None,
        detail="down",
        weight=-0.3,
    )
    decision = decide((cue,), RouterConfig(), text="is it down")
    context = _context(
        cacheable=decision.cache.cacheable,
        route=decision.route,
        service="openai",
    )
    cache = ResponseCache()

    cache.cache_response("is it down", context, "A long enough answer to cache.", salt=SALT)

    assert not decision.cache.cacheable
    assert cache.get_cached_response("is it down", context, salt=SALT) is None


@pytest.mark.asyncio
async def test_cached_response_obeys_the_decision_cache_policy():
    calls = []

    @cached_response(ttl=300.0)
    async def answer(request):
        calls.append(request.message)
        return f"answer for {request.message}"

    request = AIRequest(
        message="a cacheable question",
        user=object(),
        conversation_manager=None,
        logger=logging.getLogger("cache-routing-test"),
        routing=RoutingMetadata(
            service="openai",
            router_id="heuristic@1",
            policy_version="1",
            decision_source="structural",
            route="local",
            salt=SALT,
            cacheable=False,
        ),
    )

    first = await answer(request)
    second = await answer(request)

    assert first == second
    assert len(calls) == 2

    cacheable = AIRequest(
        message="another question",
        user=object(),
        conversation_manager=None,
        logger=logging.getLogger("cache-routing-test"),
        routing=RoutingMetadata(
            service="openai",
            router_id="heuristic@1",
            policy_version="1",
            decision_source="structural",
            route="local",
            salt=SALT,
        ),
    )
    await answer(cacheable)
    await answer(cacheable)

    assert calls.count(cacheable.message) == 1
