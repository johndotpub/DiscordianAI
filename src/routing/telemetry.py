"""Content-free log fields for a routing decision."""

from typing import Any

from .contracts import RouteDecision
from .services import SERVICE_BY_ROUTE


def decision_log_fields(decision: RouteDecision) -> dict[str, Any]:
    """Return the structured fields for one decision without message content."""
    return {
        "route": decision.route,
        "service": SERVICE_BY_ROUTE[decision.route],
        "router_id": decision.router_id,
        "reasons": ",".join(decision.reasons),
        "latency_ms": decision.latency_ms,
    }
