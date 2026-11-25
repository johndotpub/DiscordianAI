"""The optional Clef decision-model router.

Clef answers one yes/no question about the current message and, on any
transport or response failure, defers to the deterministic gate.
"""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import TYPE_CHECKING

import httpx

from .contracts import RouteDecision
from .heuristic import HeuristicRouter

if TYPE_CHECKING:
    from .contracts import RouterInput

_LOGGER = logging.getLogger(__name__)

_ENDPOINT = "/v1/systemone"
_QUESTION = "needs_live_web"
_PRIOR_TURN_LIMIT = 2
_TURN_CHAR_LIMIT = 600
_MAX_CONNECTIONS = 4
_MAX_KEEPALIVE_CONNECTIONS = 2
_INSTRUCTIONS = (
    "Does answering the user's message require current, live information from "
    "the web (e.g. current events, prices, schedules, releases, service status, "
    "who currently holds a role)?"
)
_TRUE_CRITERION = "A correct answer needs up-to-date facts from the live web."
_FALSE_CRITERION = (
    "Static knowledge suffices: general knowledge, code, opinions, creative "
    "writing, or questions whose answer does not change over time."
)
_FAILURES = (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError)


class ClefRouter:
    """Route with one Clef probability, falling back to the deterministic gate."""

    router_id = "clef"
    policy_version = "1"

    def __init__(  # noqa: PLR0913 - keyword-only connection settings mirror the router options
        self,
        *,
        api_key: str,
        model: str = "clef",
        threshold: float = 0.5,
        timeout_s: float = 2.0,
        base_url: str = "https://ollama.com",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create a Clef router.

        Args:
            api_key: Ollama Cloud API key sent as a bearer token.
            model: Decision model identifier.
            threshold: Probability at or above which the route is web.
            timeout_s: Hard total deadline for one asynchronous decision.
            base_url: Ollama Cloud base URL without the API path.
            http_client: Optional pooled client; the router owns and closes it.
        """
        self._api_key = api_key
        self._model = model
        self._threshold = threshold
        self._timeout_s = timeout_s
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client
        self._closed = False
        self._closed_reported = False

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision for ``request`` within one hard deadline."""
        gate = HeuristicRouter().decide_sync(request)
        if gate.deterministic_override:
            return gate
        started = perf_counter()
        if self._closed:
            return self._closed_fallback(request, gate, started)
        try:
            response = await asyncio.wait_for(self._post(request), timeout=self._timeout_s)
            return self._decision(request, response, started)
        except _FAILURES as exc:
            return self._fallback(request, gate, started, exc)

    def decide_sync(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision synchronously for tests and offline runs."""
        gate = HeuristicRouter().decide_sync(request)
        if gate.deterministic_override:
            return gate
        started = perf_counter()
        if self._closed:
            return self._closed_fallback(request, gate, started)
        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout_s)) as client:
                response = client.post(
                    self._url(),
                    json=self._payload(request),
                    headers=self._headers(),
                )
            return self._decision(request, response, started)
        except _FAILURES as exc:
            return self._fallback(request, gate, started, exc)

    async def aclose(self) -> None:
        """Close the router's pooled HTTP client and refuse to reopen it."""
        self._closed = True
        client = self._http_client
        self._http_client = None
        if client is not None:
            await client.aclose()

    async def _post(self, request: RouterInput) -> httpx.Response:
        client = self._client()
        return await client.post(
            self._url(),
            json=self._payload(request),
            headers=self._headers(),
        )

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_s),
                limits=httpx.Limits(
                    max_connections=_MAX_CONNECTIONS,
                    max_keepalive_connections=_MAX_KEEPALIVE_CONNECTIONS,
                ),
            )
        return self._http_client

    def _url(self) -> str:
        return f"{self._base_url}{_ENDPOINT}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, request: RouterInput) -> dict[str, object]:
        return {
            "model": self._model,
            "state": _state(request),
            "questions": {
                _QUESTION: {
                    "type": "noul",
                    "instructions": _INSTRUCTIONS,
                    "criteria": {"true": _TRUE_CRITERION, "false": _FALSE_CRITERION},
                }
            },
        }

    def _decision(
        self,
        request: RouterInput,
        response: httpx.Response,
        started: float,
    ) -> RouteDecision:
        response.raise_for_status()
        payload = response.json()
        probability = float(payload["answers"][_QUESTION]["noul"])
        route = "web" if probability >= self._threshold else "local"
        latency_ms = (perf_counter() - started) * 1000.0
        return RouteDecision(
            route=route,
            reasons=(f"clef:{route}:p={probability:.3f}",),
            latency_ms=latency_ms,
            text=request.text,
            router_id=self.router_id,
            policy_version=self.policy_version,
        )

    def _fallback(
        self,
        request: RouterInput,
        gate: RouteDecision,
        started: float,
        exc: Exception,
    ) -> RouteDecision:
        _LOGGER.warning(
            "Clef routing failed (%s); using the deterministic gate",
            type(exc).__name__,
        )
        return self._gate_result(request, gate, started, _failure_reason(exc))

    def _closed_fallback(
        self,
        request: RouterInput,
        gate: RouteDecision,
        started: float,
    ) -> RouteDecision:
        if not self._closed_reported:
            _LOGGER.warning("Clef router is closed; using the deterministic gate")
            self._closed_reported = True
        return self._gate_result(request, gate, started, "closed")

    def _gate_result(
        self,
        request: RouterInput,
        gate: RouteDecision,
        started: float,
        reason: str,
    ) -> RouteDecision:
        latency_ms = (perf_counter() - started) * 1000.0
        return RouteDecision(
            route=gate.route,
            reasons=(f"clef:fallback:{reason}", *gate.reasons),
            latency_ms=latency_ms,
            text=gate.text or request.text,
            router_id=self.router_id,
            policy_version=self.policy_version,
        )


def _state(request: RouterInput) -> str:
    turns = request.context.turns[-_PRIOR_TURN_LIMIT:]
    lines = ["Conversation so far:"] if turns else []
    for turn in turns:
        marker = "u" if turn.role == "user" else "a"
        lines.append(f"{marker}: {turn.text[:_TURN_CHAR_LIMIT]}")
    if lines:
        lines.append("")
    lines.extend(("User message:", request.text))
    return "\n".join(lines)


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "transport"
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return "malformed"
    return "error"
