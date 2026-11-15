"""Content-free log fields for a routing decision."""

from typing import Any

from .contracts import RouteDecision

_SERVICE_BY_ROUTE = {"web": "perplexity", "local": "openai"}


def decision_log_fields(decision: RouteDecision) -> dict[str, Any]:
    """Return the structured fields for one decision without message content."""
    return {
        "route": decision.route,
        "service": _SERVICE_BY_ROUTE[decision.route],
        "reasons": ",".join(decision.reasons),
        "latency_ms": decision.latency_ms,
    }
