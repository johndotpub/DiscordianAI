"""Provider-neutral request, result, and protocol definitions.

The protocol is deliberately small: an adapter turns one :class:`CompletionRequest`
into one :class:`ProviderResult`, or raises. Tool calls are resolved inside the
adapter that offered them; callers never see an intermediate tool-call response.
Citations are empty unless the provider itself yields source metadata.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


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


@dataclass(frozen=True)
class ProviderResult:
    """A provider answer after adapter-side parsing.

    Attributes:
        text: Assistant text. An empty string means the provider answered with
            no usable text; the caller decides whether that is a failure.
        citations: Citation number to URL mapping. Empty for providers that do
            not return citation metadata.
        finish_reason: Provider finish reason when one is available.
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
        ...

    async def probe(self) -> ProbeResult:
        """Check provider reachability without changing user-visible state."""
        ...
