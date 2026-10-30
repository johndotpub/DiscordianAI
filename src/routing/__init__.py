"""Routing contracts, heuristic scoring, and the package factory."""

from collections.abc import Mapping
import os
from typing import Any

from .contracts import (
    Band,
    CachePolicy,
    ConversationContext,
    Evidence,
    EvidenceClass,
    Route,
    RouteDecision,
    Router,
    RouterConfig,
    RouterInput,
    Source,
    Turn,
)
from .features import ExplicitRoute, parse_explicit_route
from .heuristic import HeuristicRouter
from .scoring import Score, decide, score
from .telemetry import decision_log_fields

__all__ = [
    "Band",
    "CachePolicy",
    "ConversationContext",
    "Evidence",
    "EvidenceClass",
    "ExplicitRoute",
    "HeuristicRouter",
    "Route",
    "RouteDecision",
    "Router",
    "RouterConfig",
    "RouterInput",
    "Score",
    "Source",
    "Turn",
    "build_router",
    "decide",
    "decision_log_fields",
    "parse_explicit_route",
    "score",
]


def build_router(config: Any = None) -> Router:
    """Return the configured router implementation.

    Only the heuristic router exists today. Selecting the optional model
    implementation raises rather than silently falling back, because the Clef
    seam is specified but not built: see ``docs/routing/DESIGN.md``.
    """
    mode = str(_config_value(config, "ROUTER_MODE", "heuristic")).strip().lower()
    if mode == "model":
        msg = (
            "ROUTER_MODE=model is not implemented; the Clef seam is described "
            "in docs/routing/DESIGN.md"
        )
        raise NotImplementedError(msg)
    if mode != "heuristic":
        msg = f"Unknown ROUTER_MODE {mode!r}; expected 'heuristic' or 'model'"
        raise ValueError(msg)
    return HeuristicRouter(
        config=RouterConfig(
            router_id=HeuristicRouter.router_id,
            policy_version=HeuristicRouter.policy_version,
        )
    )


def _config_value(config: Any, key: str, default: Any) -> Any:
    missing = object()
    if isinstance(config, Mapping):
        value = config.get(key, missing)
    elif config is not None:
        value = getattr(config, key, missing)
    else:
        value = missing
    if value is not missing:
        return value
    return os.environ.get(key, default)
