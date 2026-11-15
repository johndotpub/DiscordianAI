"""Routing contracts, the deterministic gate, and the package factory."""

from collections.abc import Mapping
import os
from typing import Any

from .contracts import (
    ConversationContext,
    EvidenceClass,
    Route,
    RouteDecision,
    Router,
    RouterInput,
    Source,
    Turn,
)
from .gate import decide
from .heuristic import HeuristicRouter
from .telemetry import decision_log_fields

__all__ = [
    "ConversationContext",
    "EvidenceClass",
    "HeuristicRouter",
    "Route",
    "RouteDecision",
    "Router",
    "RouterInput",
    "Source",
    "Turn",
    "build_router",
    "decide",
    "decision_log_fields",
]


def build_router(config: Any = None) -> Router:
    """Return the configured router implementation.

    Only the heuristic gate exists today. Selecting the optional model
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
    return HeuristicRouter()


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
