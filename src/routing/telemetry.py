"""Content-free log fields for a routing decision."""

from typing import Any

from .contracts import RouteDecision

_MAX_REASONS = 5
_SERVICE_BY_ROUTE = {"web": "perplexity", "local": "openai"}


def decision_log_fields(decision: RouteDecision) -> dict[str, Any]:
    """Return the structured fields for one decision without message content."""
    reasons: list[str] = []
    for item in decision.evidence:
        if item.signal not in reasons:
            reasons.append(item.signal)
        if len(reasons) == _MAX_REASONS:
            break
    return {
        "route": decision.route,
        "band": decision.band,
        "service": _SERVICE_BY_ROUTE[decision.route],
        "score": decision.score,
        "threshold": decision.threshold,
        "reasons": reasons,
        "router_id": decision.router_id,
        "policy_version": decision.policy_version,
        "latency_ms": decision.latency_ms,
    }
