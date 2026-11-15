"""Routing contracts, the deterministic gate, and the package factory."""

from collections.abc import Mapping
import logging
import math
import os
from typing import Any

from .clef import ClefRouter
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
    "ClefRouter",
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

_LOGGER = logging.getLogger(__name__)
_DEFAULT_CLEF_MODEL = "clef"
_DEFAULT_CLEF_THRESHOLD = 0.5
_DEFAULT_CLEF_TIMEOUT_MS = 2000


def build_router(config: Any = None) -> Router:
    """Return the configured router implementation.

    ``heuristic`` is the default deterministic gate. ``clef`` builds the
    optional decision-model router when a key is available; it falls back to
    the gate when no key is configured. ``model`` is rejected by name so an old
    configuration fails loudly instead of silently changing routers.
    """
    mode = str(_config_value(config, "ROUTER_MODE", "heuristic")).strip().lower()
    if mode == "clef":
        return _build_clef_router(config)
    if mode == "model":
        msg = "ROUTER_MODE=model is not implemented; use ROUTER_MODE=clef"
        raise NotImplementedError(msg)
    if mode != "heuristic":
        msg = f"Unknown ROUTER_MODE {mode!r}; expected 'heuristic', 'clef', or 'model'"
        raise ValueError(msg)
    return HeuristicRouter()


def _build_clef_router(config: Any) -> Router:
    api_key = _first_config_or_env(config, ("OPENAI_API_KEY", "OLLAMA_API_KEY"))
    if api_key is None:
        _LOGGER.warning(
            "ROUTER_MODE=clef needs OPENAI_API_KEY or OLLAMA_API_KEY; "
            "using the deterministic gate"
        )
        return HeuristicRouter()

    model = str(_config_value(config, "ROUTER_CLEF_MODEL", _DEFAULT_CLEF_MODEL)).strip()
    if not model:
        _LOGGER.warning("ROUTER_CLEF_MODEL is empty; using %s", _DEFAULT_CLEF_MODEL)
        model = _DEFAULT_CLEF_MODEL

    return ClefRouter(
        api_key=api_key,
        model=model,
        threshold=_clef_threshold(config),
        timeout_s=_clef_timeout_s(config),
    )


def _clef_threshold(config: Any) -> float:
    raw = _config_value(config, "ROUTER_CLEF_THRESHOLD", _DEFAULT_CLEF_THRESHOLD)
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_THRESHOLD %r; using %s",
            raw,
            _DEFAULT_CLEF_THRESHOLD,
        )
        return _DEFAULT_CLEF_THRESHOLD
    if not math.isfinite(threshold):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_THRESHOLD %r; using %s",
            raw,
            _DEFAULT_CLEF_THRESHOLD,
        )
        return _DEFAULT_CLEF_THRESHOLD
    if threshold < 0.0 or threshold > 1.0:
        clamped = min(1.0, max(0.0, threshold))
        _LOGGER.warning(
            "ROUTER_CLEF_THRESHOLD %s is outside [0, 1]; using %s",
            threshold,
            clamped,
        )
        return clamped
    return threshold


def _clef_timeout_s(config: Any) -> float:
    raw = _config_value(config, "ROUTER_CLEF_TIMEOUT_MS", _DEFAULT_CLEF_TIMEOUT_MS)
    try:
        timeout_ms = float(raw)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_TIMEOUT_MS %r; using %s",
            raw,
            _DEFAULT_CLEF_TIMEOUT_MS,
        )
        return _DEFAULT_CLEF_TIMEOUT_MS / 1000.0
    if not math.isfinite(timeout_ms) or timeout_ms <= 0.0:
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_TIMEOUT_MS %r; using %s",
            raw,
            _DEFAULT_CLEF_TIMEOUT_MS,
        )
        return _DEFAULT_CLEF_TIMEOUT_MS / 1000.0
    return timeout_ms / 1000.0


def _first_config_or_env(config: Any, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _config_present(config, key)
        if value is not None and str(value).strip():
            return str(value).strip()
        env_value = os.environ.get(key)
        if env_value is not None and env_value.strip():
            return env_value.strip()
    return None


def _config_present(config: Any, key: str) -> Any:
    if isinstance(config, Mapping):
        return config.get(key)
    if config is not None:
        return getattr(config, key, None)
    return None


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
