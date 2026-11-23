"""Clef's request shape, threshold, and deterministic fallback."""

import logging

import httpx
import pytest

from src.routing import ClefRouter, HeuristicRouter, build_router
from src.routing.contracts import ConversationContext, RouterInput, Turn

_ENDPOINT = "https://ollama.com/v1/systemone"


@pytest.fixture(autouse=True)
def reset_missing_clef_key_warning():
    """Keep the once-per-process missing-key warning isolated between tests."""
    from src.routing import _warn_missing_clef_key_once

    _warn_missing_clef_key_once.cache_clear()
    yield
    _warn_missing_clef_key_once.cache_clear()


class _FakeAsyncClient:
    def __init__(self):
        self.calls = []
        self.closed = 0

    async def post(self, url, *, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _response(0.9)

    async def aclose(self):
        self.closed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False


def _response(probability: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "clef",
            "answers": {"needs_live_web": {"type": "noul", "noul": probability}},
            "usage": {},
        },
        request=httpx.Request("POST", _ENDPOINT),
    )


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"error": "upstream failed"},
        request=httpx.Request("POST", _ENDPOINT),
    )


def _install_sync(monkeypatch, response):
    calls: list[dict] = []

    def fake_post(_client, url, *, json=None, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return calls


def _install_async(monkeypatch, response):
    calls: list[dict] = []

    async def fake_post(_client, url, *, json=None, headers=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def test_web_decision_sends_one_noul_question(monkeypatch) -> None:
    """A high probability routes web and the payload names the single question."""
    calls = _install_sync(monkeypatch, _response(0.977))

    decision = ClefRouter(api_key="test-key").decide_sync(
        RouterInput(text="is the github site down right now?")
    )

    assert decision.route == "web"
    assert decision.reasons == ("clef:web:p=0.977",)
    assert decision.text == "is the github site down right now?"
    assert calls[0]["url"] == _ENDPOINT
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    question = calls[0]["json"]["questions"]["needs_live_web"]
    assert calls[0]["json"]["model"] == "clef"
    assert question["type"] == "noul"
    assert "live information" in question["instructions"]
    assert set(question["criteria"]) == {"true", "false"}


def test_local_decision_keeps_the_probability_in_the_reason(monkeypatch) -> None:
    """A low probability routes local with the measured probability."""
    _install_sync(monkeypatch, _response(0.123))

    decision = ClefRouter(api_key="test-key").decide_sync(
        RouterInput(text="write me a haiku about autumn")
    )

    assert decision.route == "local"
    assert decision.reasons == ("clef:local:p=0.123",)
    assert decision.router_id == "clef"
    assert decision.policy_version == "1"


def test_fallback_decision_carries_the_clef_identity(monkeypatch) -> None:
    """A fallback answer is still produced under Clef's cache identity."""
    _install_sync(
        monkeypatch,
        httpx.ConnectError("offline", request=httpx.Request("POST", _ENDPOINT)),
    )

    decision = ClefRouter(api_key="test-key").decide_sync(RouterInput(text="is github down"))

    assert decision.router_id == "clef"
    assert decision.policy_version == "1"


@pytest.mark.asyncio
async def test_async_decide_uses_the_same_contract(monkeypatch) -> None:
    """The async path returns the same decision from the same payload."""
    calls = _install_async(monkeypatch, _response(0.977))

    decision = await ClefRouter(api_key="test-key").decide(
        RouterInput(text="is the github site down right now?")
    )

    assert decision.route == "web"
    assert decision.reasons == ("clef:web:p=0.977",)
    assert calls[0]["url"] == _ENDPOINT


@pytest.mark.parametrize(
    ("probability", "expected"),
    [(0.5, "web"), (0.499, "local")],
)
def test_threshold_boundary_is_inclusive(monkeypatch, probability, expected) -> None:
    """A probability equal to the threshold routes web; just below stays local."""
    _install_sync(monkeypatch, _response(probability))

    decision = ClefRouter(api_key="test-key", threshold=0.5).decide_sync(
        RouterInput(text="is github down")
    )

    assert decision.route == expected


def test_state_carries_only_the_last_two_turns_and_truncates_them(monkeypatch) -> None:
    """Prior turns are bounded and the current message stays separate."""
    calls = _install_sync(monkeypatch, _response(0.9))
    turns = (
        Turn(role="user", text="dropped first turn"),
        Turn(role="assistant", text="kept second turn"),
        Turn(role="user", text="x" * 700),
    )

    ClefRouter(api_key="test-key").decide_sync(
        RouterInput(
            text="current question",
            context=ConversationContext(turns=turns),
        )
    )

    state = calls[0]["json"]["state"]
    assert "dropped first turn" not in state
    assert "a: kept second turn" in state
    assert "x" * 600 in state
    assert "x" * 601 not in state
    assert state.endswith("User message:\ncurrent question")


def test_url_override_skips_clef(monkeypatch) -> None:
    """An explicit URL is decided by the gate without any HTTP call."""
    calls = _install_sync(
        monkeypatch,
        AssertionError("Clef must not be consulted for an override"),
    )
    request = RouterInput(text="check https://example.com for me")
    expected = HeuristicRouter().decide_sync(request)

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert calls == []
    assert decision.route == "web"
    assert decision.reasons == expected.reasons
    assert any(reason.startswith("override:") for reason in decision.reasons)
    assert decision.text == request.text


def test_local_instruction_override_skips_clef(monkeypatch) -> None:
    """An explicit local-only instruction is decided by the gate alone."""
    calls = _install_sync(
        monkeypatch,
        AssertionError("Clef must not be consulted for an override"),
    )
    request = RouterInput(text="answer from memory")
    expected = HeuristicRouter().decide_sync(request)

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert calls == []
    assert decision.route == "local"
    assert decision.reasons == expected.reasons
    assert "override:local_instruction" in decision.reasons


@pytest.mark.asyncio
async def test_async_override_skips_clef(monkeypatch) -> None:
    """The async path also returns the gate decision before calling Clef."""
    calls = _install_async(
        monkeypatch,
        AssertionError("Clef must not be consulted for an override"),
    )
    request = RouterInput(text="check https://example.com for me")

    decision = await ClefRouter(api_key="test-key").decide(request)

    assert calls == []
    assert decision.route == "web"
    assert decision.reasons == ("override:url",)


def test_ordinary_message_still_consults_clef(monkeypatch) -> None:
    """Without an override, Clef remains the judge even when the gate is local."""
    calls = _install_sync(monkeypatch, _response(0.977))

    decision = ClefRouter(api_key="test-key").decide_sync(RouterInput(text="tell me about monads"))

    assert len(calls) == 1
    assert decision.route == "web"
    assert decision.reasons == ("clef:web:p=0.977",)


def test_override_returns_gate_decision_without_a_fallback_marker(monkeypatch) -> None:
    """A failing Clef is never consulted when an override is present."""
    calls = _install_sync(
        monkeypatch,
        httpx.ConnectError("offline", request=httpx.Request("POST", _ENDPOINT)),
    )
    request = RouterInput(text="search the web for is github down")
    expected = HeuristicRouter().decide_sync(request)

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert calls == []
    assert decision.route == "web"
    assert decision.reasons == expected.reasons
    assert not any(reason.startswith("clef:fallback:") for reason in decision.reasons)


def test_http_500_falls_back_to_the_deterministic_gate(monkeypatch, caplog) -> None:
    """An HTTP failure is marked as a Clef fallback and keeps the gate's route."""
    _install_sync(monkeypatch, _status_response(500))
    request = RouterInput(text="is github down")
    expected = HeuristicRouter().decide_sync(request)

    with caplog.at_level(logging.WARNING, logger="src.routing.clef"):
        decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert decision.route == expected.route == "web"
    assert decision.reasons[0] == "clef:fallback:http_500"
    assert decision.reasons[1:] == expected.reasons
    assert decision.text == expected.text
    assert decision.latency_ms >= 0.0
    assert any("Clef routing failed" in record.getMessage() for record in caplog.records)


def test_malformed_json_falls_back_to_the_deterministic_gate(monkeypatch) -> None:
    """A response without the expected fields never escapes as an exception."""
    response = httpx.Response(
        200,
        content=b"not json",
        request=httpx.Request("POST", _ENDPOINT),
    )
    _install_sync(monkeypatch, response)
    request = RouterInput(text="write me a haiku about autumn")
    expected = HeuristicRouter().decide_sync(request)

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert decision.route == expected.route
    assert decision.reasons[0] == "clef:fallback:malformed"
    assert decision.reasons[1:] == expected.reasons


def test_transport_error_falls_back_to_the_deterministic_gate(monkeypatch) -> None:
    """A connection failure is a fallback, not a failed request."""
    _install_sync(
        monkeypatch,
        httpx.ConnectError("offline", request=httpx.Request("POST", _ENDPOINT)),
    )
    request = RouterInput(text="is github down")

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert decision.route == "web"
    assert decision.reasons[0] == "clef:fallback:transport"


def test_missing_key_warns_and_builds_the_heuristic(monkeypatch, caplog) -> None:
    """Clef without a key stays usable through the deterministic gate."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="src.routing"):
        router = build_router({"ROUTER_MODE": "clef", "OPENAI_API_KEY": None})

    assert isinstance(router, HeuristicRouter)
    assert any("OPENAI_API_KEY" in record.getMessage() for record in caplog.records)


def test_ollama_key_is_accepted_when_openai_key_is_absent(monkeypatch) -> None:
    """The fallback key variable builds the same Clef router."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-key")

    router = build_router({"ROUTER_MODE": "clef"})

    assert isinstance(router, ClefRouter)


def test_build_router_selects_clef_and_clamps_the_threshold(monkeypatch) -> None:
    """A threshold above one clamps to one, so certainty still routes web."""
    _install_sync(monkeypatch, _response(1.0))

    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "OPENAI_API_KEY": "test-key",
            "ROUTER_CLEF_THRESHOLD": 2.0,
            "ROUTER_CLEF_TIMEOUT_MS": 500,
        }
    )
    decision = router.decide_sync(RouterInput(text="is github down"))

    assert isinstance(router, ClefRouter)
    assert decision.route == "web"
    assert decision.reasons == ("clef:web:p=1.000",)


def test_model_mode_raises_with_the_new_message() -> None:
    """The retired mode points at Clef rather than at an unbuilt seam."""
    with pytest.raises(NotImplementedError) as excinfo:
        build_router({"ROUTER_MODE": "model"})

    assert str(excinfo.value) == "ROUTER_MODE=model is not implemented; use ROUTER_MODE=clef"


def test_unknown_mode_raises() -> None:
    """An unknown mode is rejected instead of selecting a router."""
    with pytest.raises(ValueError) as excinfo:
        build_router({"ROUTER_MODE": "magic"})

    assert "expected 'heuristic', 'clef', or 'model'" in str(excinfo.value)


def test_supplied_artifact_override_skips_clef(monkeypatch) -> None:
    """A gate artifact decision is data, so Clef must not flip it to web."""
    calls = _install_sync(monkeypatch, _response(0.99))
    request = RouterInput(text="summarize: the api is down and the version is 2.0")
    expected = HeuristicRouter().decide_sync(request)

    decision = ClefRouter(api_key="test-key").decide_sync(request)

    assert calls == []
    assert decision.route == expected.route == "local"
    assert decision.reasons == expected.reasons
    assert decision.deterministic_override is True


def test_dedicated_clef_key_wins_over_the_chat_key(monkeypatch) -> None:
    """The dedicated key is used even when the chat provider has another key."""
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-env-key")
    calls = _install_sync(monkeypatch, _response(0.9))
    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "ROUTER_CLEF_API_KEY": "clef-key",
            "OPENAI_API_KEY": "sk-openai",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
        }
    )

    router.decide_sync(RouterInput(text="tell me about monads"))

    assert calls[0]["headers"]["Authorization"] == "Bearer clef-key"


def test_dedicated_clef_key_can_come_from_the_environment(monkeypatch) -> None:
    """The dedicated key is also accepted through its environment variable."""
    monkeypatch.setenv("ROUTER_CLEF_API_KEY", "env-clef-key")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    calls = _install_sync(monkeypatch, _response(0.9))
    router = build_router({"ROUTER_MODE": "clef", "OPENAI_API_URL": "https://api.openai.com/v1/"})

    router.decide_sync(RouterInput(text="tell me about monads"))

    assert calls[0]["headers"]["Authorization"] == "Bearer env-clef-key"


def test_openai_key_is_not_sent_to_clef_for_another_host(monkeypatch) -> None:
    """A key issued for another provider never reaches the Clef endpoint."""
    monkeypatch.delenv("ROUTER_CLEF_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "OPENAI_API_KEY": "sk-openai",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
        }
    )

    assert isinstance(router, HeuristicRouter)


def test_ollama_cloud_chat_key_still_builds_clef(monkeypatch) -> None:
    """An existing Ollama Cloud deployment keeps working without a new key."""
    monkeypatch.delenv("ROUTER_CLEF_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    calls = _install_sync(monkeypatch, _response(0.9))
    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "OPENAI_API_KEY": "ollama-cloud-key",
            "OPENAI_API_URL": "https://ollama.com/v1/",
        }
    )

    assert isinstance(router, ClefRouter)
    router.decide_sync(RouterInput(text="tell me about monads"))
    assert calls[0]["headers"]["Authorization"] == "Bearer ollama-cloud-key"


def test_ollama_environment_key_is_eligible_for_another_chat_host(monkeypatch) -> None:
    """An Ollama Cloud key from the environment may still reach Ollama."""
    monkeypatch.delenv("ROUTER_CLEF_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-env-key")
    calls = _install_sync(monkeypatch, _response(0.9))
    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "OPENAI_API_KEY": "sk-openai",
            "OPENAI_API_URL": "https://api.openai.com/v1/",
        }
    )

    router.decide_sync(RouterInput(text="tell me about monads"))

    assert calls[0]["headers"]["Authorization"] == "Bearer ollama-env-key"


def test_missing_key_warning_is_emitted_once(monkeypatch, caplog) -> None:
    """Repeated factory calls do not log the missing-key warning per message."""
    monkeypatch.delenv("ROUTER_CLEF_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="src.routing"):
        build_router({"ROUTER_MODE": "clef"})
        build_router({"ROUTER_MODE": "clef"})

    warnings = [record for record in caplog.records if "no eligible key" in record.getMessage()]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_async_decisions_reuse_one_pooled_client(monkeypatch) -> None:
    """One router keeps one client for every decision and closes it once."""
    created = []

    class _CountingClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)
            super().__init__()
            created.append(self)

    monkeypatch.setattr("src.routing.clef.httpx.AsyncClient", _CountingClient)
    router = ClefRouter(api_key="test-key")

    await router.decide(RouterInput(text="tell me about monads"))
    await router.decide(RouterInput(text="tell me about functors"))

    assert len(created) == 1
    assert len(created[0].calls) == 2
    assert created[0].closed == 0
    await router.aclose()
    assert created[0].closed == 1
    await router.aclose()
    assert created[0].closed == 1


@pytest.mark.asyncio
async def test_clef_deadline_wraps_the_whole_request(monkeypatch) -> None:
    """The configured timeout is one hard deadline, not a per-phase budget."""
    recorded = {"timeout": None}

    async def fake_wait_for(awaitable, **kwargs):
        recorded["timeout"] = kwargs["timeout"]
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("src.routing.clef.asyncio.wait_for", fake_wait_for)
    router = ClefRouter(
        api_key="test-key",
        timeout_s=2.0,
        http_client=_FakeAsyncClient(),
    )

    decision = await router.decide(RouterInput(text="tell me about monads"))

    assert recorded["timeout"] == 2.0
    assert decision.reasons[0] == "clef:fallback:timeout"
