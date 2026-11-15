"""Branch coverage for the web-tool plumbing and Clef glue."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src import openai_processing, web_tools
from src.routing import build_router
from src.routing.clef import ClefRouter
from src.routing.heuristic import HeuristicRouter


class TestShouldOfferWebTools:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://ollama.com/v1", True),
            ("https://eu.ollama.com", True),
            ("http://localhost:11434/v1", True),
            ("http://127.0.0.1:11434/v1", True),
            ("https://api.openai.com/v1", False),
            ("https://ollama.com.evil.com", False),
            ("", False),
            ("not a url", False),
        ],
    )
    def test_hosts(self, url, expected):
        assert web_tools.should_offer_web_tools(url) is expected


class _FakeClient:
    """Stand-in for httpx.AsyncClient capturing the outgoing request."""

    def __init__(self, *, payload=None, status=200, exc=None):
        self.payload = payload if payload is not None else {}
        self.status = status
        self.exc = exc
        self.requests = []

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        request = httpx.Request("POST", url)
        return httpx.Response(self.status, json=self.payload, request=request)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(web_tools.httpx, "AsyncClient", lambda *_a, **_k: fake)


@pytest.mark.asyncio
async def test_web_search_defaults_max_results_when_not_an_int(monkeypatch):
    fake = _FakeClient(payload={"results": [{"title": "T", "url": "u", "content": "c"}]})
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_search",
        '{"query": "news", "max_results": "abc"}',
        api_key="k",
        base_url="https://ollama.com",
    )
    assert fake.requests[0][1]["json"]["max_results"] == 5
    assert "T" in out
    assert "u" in out


@pytest.mark.asyncio
async def test_web_search_requires_query(monkeypatch):
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_search", "{}", api_key="k", base_url="https://ollama.com"
    )
    assert "error" in out
    assert fake.requests == []


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_envelope(monkeypatch):
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool("nope", "{}", api_key="k", base_url="https://ollama.com")
    assert "error" in out


@pytest.mark.asyncio
async def test_http_500_returns_error_envelope(monkeypatch):
    fake = _FakeClient(status=500, payload={"error": "boom"})
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_fetch", '{"url": "https://x"}', api_key="k", base_url="https://ollama.com"
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_transport_error_returns_error_envelope(monkeypatch):
    fake = _FakeClient(exc=httpx.ConnectError("nope"))
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_search", '{"query": "q"}', api_key="k", base_url="https://ollama.com"
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_invalid_json_arguments_return_error_envelope(monkeypatch):
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_search", "not-json", api_key="k", base_url="https://ollama.com"
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_web_search_output_is_truncated(monkeypatch):
    big = [
        {"title": "t" * 5000, "url": f"https://e.com/{i}", "content": "c" * 5000}
        for i in range(10)
    ]
    fake = _FakeClient(payload={"results": big})
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_search",
        '{"query": "q", "max_results": 10}',
        api_key="k",
        base_url="https://ollama.com",
    )
    assert len(out) <= 6200


@pytest.mark.asyncio
async def test_web_fetch_output_is_truncated(monkeypatch):
    fake = _FakeClient(payload={"title": "T", "content": "x" * 20000})
    _patch_client(monkeypatch, fake)
    out = await web_tools.call_web_tool(
        "web_fetch", '{"url": "https://e.com"}', api_key="k", base_url="https://ollama.com"
    )
    assert len(out) <= 8200


def test_object_field_reads_mapping_and_object():
    assert openai_processing._object_field({"a": 1}, "a") == 1
    assert openai_processing._object_field(SimpleNamespace(a=2), "a") == 2
    assert openai_processing._object_field({}, "missing", "dflt") == "dflt"


def test_tool_result_ok_handles_unparseable_payload():
    assert openai_processing._tool_result_ok("not json at all") is True
    assert openai_processing._tool_result_ok('{"error": "x"}') is False
    assert openai_processing._tool_result_ok('{"ok": true}') is True


def test_tool_call_payload_normalises_missing_fields():
    call = {"function": {"name": "web_search"}}
    payload = openai_processing._tool_call_payload(call)
    assert payload["type"] == "function"
    assert payload["function"]["arguments"] == "{}"


@pytest.mark.asyncio
async def test_invalid_final_response_structure_returns_none(make_request):
    from src.models import OpenAIConfig

    client = MagicMock()
    client.base_url = "https://ollama.com/v1"
    client.api_key = "k"
    client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[]))
    result = await openai_processing.process_openai_message(
        request=make_request("hi", conversation_manager=MagicMock(), logger=MagicMock()),
        conversation_summary=[],
        openai_client=client,
        config=OpenAIConfig(),
    )
    assert result is None


class TestClefRouterFailures:
    def test_failure_reason_taxonomy(self):
        from http import HTTPStatus

        from src.routing.clef import _failure_reason

        request = httpx.Request("POST", "https://ollama.com/v1/systemone")
        resp = httpx.Response(HTTPStatus.INTERNAL_SERVER_ERROR, request=request)
        assert (
            _failure_reason(httpx.HTTPStatusError("x", request=request, response=resp))
            == "http_500"
        )
        assert _failure_reason(httpx.ReadTimeout("t")) == "timeout"
        assert _failure_reason(httpx.ConnectError("c")) == "transport"
        assert _failure_reason(KeyError("answers")) == "malformed"
        assert _failure_reason(RuntimeError("other")) == "error"

    @pytest.mark.asyncio
    async def test_async_failure_falls_back(self, monkeypatch):
        router = ClefRouter(api_key="test-key")

        async def boom(*args, **kwargs):
            msg = "down"
            raise httpx.ConnectError(msg)

        class _Boom:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            post = boom

        monkeypatch.setattr("src.routing.clef.httpx.AsyncClient", _Boom)

        from src.routing.context import build_router_input

        req = build_router_input(
            SimpleNamespace(message="hello there friend", conversation_key=None),
            None,
            6,
        )
        decision = await router.decide(req)
        assert decision.reasons[0].startswith("clef:fallback:transport")


class TestBuildRouterClefConfig:
    def test_invalid_threshold_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MODE", "clef")
        monkeypatch.setenv("ROUTER_CLEF_THRESHOLD", "not-a-number")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        router = build_router({})
        assert isinstance(router, ClefRouter)

    def test_out_of_range_threshold_is_clamped(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MODE", "clef")
        monkeypatch.setenv("ROUTER_CLEF_THRESHOLD", "9")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        router = build_router({})
        assert router._threshold == 1.0

    def test_invalid_timeout_falls_back(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MODE", "clef")
        monkeypatch.setenv("ROUTER_CLEF_TIMEOUT_MS", "-5")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        router = build_router({})
        assert router._timeout_s == 2.0

    def test_empty_model_falls_back(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MODE", "clef")
        monkeypatch.setenv("ROUTER_CLEF_MODEL", "  ")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        router = build_router({})
        assert router._model == "clef"

    def test_clef_without_key_uses_heuristic(self, monkeypatch):
        monkeypatch.setenv("ROUTER_MODE", "clef")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        assert isinstance(build_router({}), HeuristicRouter)
