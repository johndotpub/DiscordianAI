"""Provider-neutral request, result, and protocol definitions.

The protocol is deliberately small: an adapter turns one :class:`CompletionRequest`
into one :class:`ProviderResult`, or raises. Tool calls are resolved inside the
adapter that offered them; callers never see an intermediate tool-call response.
Citations are empty unless the provider itself yields source metadata.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import time
from typing import Any, Protocol


def object_field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK object or a plain mapping."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def model_ids_from_response(response: Any) -> list[str]:
    """Return the non-empty model ids from a ``models.list`` response."""
    return [
        model_id
        for item in object_field(response, "data", []) or []
        if (model_id := object_field(item, "id"))
    ]


async def probe_models(client: Any, timeout_s: float) -> "ProbeResult":
    """List models with one bounded timeout and return a reachability result."""
    started_at = time.monotonic()
    try:
        response = await asyncio.wait_for(client.models.list(), timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 - probes report, never raise
        latency_ms = (time.monotonic() - started_at) * 1000
        return ProbeResult(
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            latency_ms=round(latency_ms, 1),
        )

    latency_ms = (time.monotonic() - started_at) * 1000
    model_ids = model_ids_from_response(response)
    if not model_ids:
        return ProbeResult(
            ok=False,
            detail="provider returned no models",
            latency_ms=round(latency_ms, 1),
        )
    return ProbeResult(
        ok=True,
        detail=f"{len(model_ids)} models available",
        latency_ms=round(latency_ms, 1),
    )


@dataclass(frozen=True)
class CompletionRequest:
    """A normalised completion request shared by every provider adapter.

    Attributes:
        model: Provider model identifier.
        messages: Chat-shaped messages, including any system message.
        max_output_tokens: Output-token cap already resolved for this request.
        reasoning_effort: Optional reasoning-effort hint; ``None`` omits it.
        tools: Provider-specific tool schemas to offer, if any.
        extra: Adapter-specific request fields that are not part of the
            common chat shape.
    """

    model: str
    messages: list[dict]
    max_output_tokens: int
    reasoning_effort: str | None
    tools: tuple[dict, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one provider reachability probe.

    Attributes:
        ok: Whether the provider answered with a usable model listing.
        detail: Short, non-secret explanation for logs and health output.
        latency_ms: Observed round-trip time in milliseconds.
    """

    ok: bool
    detail: str
    latency_ms: float


class AssistantText(str):
    """Answer text that keeps a normalised truncation signal for delivery.

    The type is a plain ``str`` so cache lookups, history writes, and existing
    comparisons keep working. Delivery reads ``truncated`` and appends the one
    fixed length-limit notice; the notice is never part of this text or the
    conversation history.
    """

    __slots__ = ("truncated",)

    truncated: bool

    def __new__(cls, text: str, *, truncated: bool = False) -> "AssistantText":
        """Create answer text with its truncation state."""
        instance = super().__new__(cls, text)
        instance.truncated = truncated
        return instance


@dataclass(frozen=True)
class ProviderResult:
    """A provider answer after adapter-side parsing.

    Attributes:
        text: Assistant text. An empty string means the provider answered with
            no usable text; the caller decides whether that is a failure.
        citations: Citation number to URL mapping. Empty for providers that do
            not return citation metadata.
        finish_reason: Provider finish reason when one is available, normalised
            to ``"length"`` when the provider stopped at its output-token cap.
        raw: The unmodified provider response for tracing and lifecycle hooks.
    """

    text: str
    citations: Mapping[str, str] = field(default_factory=dict)
    finish_reason: str | None = None
    raw: Any = None


class AIProvider(Protocol):
    """Structural contract implemented by each provider adapter.

    ``complete`` returns text or raises; retries and circuit breaking stay with
    the adapter. ``probe`` is a read-only reachability check and must not mutate
    conversation state.
    """

    name: str
    supports_web_tools: bool

    async def complete(self, req: CompletionRequest) -> ProviderResult:
        """Return one parsed answer, resolving any client-side tool loop."""

    async def probe(self) -> ProbeResult:
        """Check provider reachability without changing user-visible state."""
