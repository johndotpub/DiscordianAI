"""Routing contracts, the deterministic gate, and the package factory."""

from collections.abc import Mapping
from functools import lru_cache
import logging
import math
import os
from typing import Any
from urllib.parse import urlsplit

from src.config import (
    DEFAULT_ROUTER_CLEF_MODEL,
    DEFAULT_ROUTER_CLEF_THRESHOLD,
    DEFAULT_ROUTER_CLEF_TIMEOUT_MS,
)

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
from .lexicon import LexiconError
from .telemetry import decision_log_fields

__all__ = [
    "ClefRouter",
    "ConversationContext",
    "EvidenceClass",
    "HeuristicRouter",
    "LocalFallbackRouter",
    "Route",
    "RouteDecision",
    "Router",
    "RouterInput",
    "Source",
    "Turn",
    "build_router",
    "decide",
    "decision_log_fields",
    "router_config_key",
]

_LOGGER = logging.getLogger(__name__)
_OLLAMA_CLOUD_HOST = "ollama.com"


class LocalFallbackRouter:
    """A deterministic local-only router used when the lexicon cannot load."""

    router_id = "gate"
    policy_version = "1"

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the local fallback decision for ``request``."""
        return self.decide_sync(request)

    def decide_sync(self, request: RouterInput) -> RouteDecision:
        """Return the local fallback decision synchronously."""
        return RouteDecision(
            route="local",
            reasons=("fallback:lexicon_error",),
            text=request.text,
        )


def build_router(config: Any = None) -> Router:
    """Return the configured router implementation.

    ``heuristic`` is the default deterministic gate. ``clef`` builds the
    optional decision-model router when an eligible key is available; it falls
    back to the gate when no key is configured. ``model`` is rejected by name so
    an old configuration fails loudly instead of silently changing routers.
    A missing or corrupt lexicon is logged at CRITICAL and replaced with a
    local-only router, so the bot keeps answering instead of aborting startup.
    """
    mode = str(_config_value(config, "ROUTER_MODE", "heuristic")).strip().lower()
    if mode == "model":
        msg = "ROUTER_MODE=model is not implemented; use ROUTER_MODE=clef"
        raise NotImplementedError(msg)
    if mode not in {"heuristic", "clef"}:
        msg = f"Unknown ROUTER_MODE {mode!r}; expected 'heuristic', 'clef', or 'model'"
        raise ValueError(msg)

    try:
        if mode == "clef":
            # Load the deterministic gate's lexicon now. Clef itself consults
            # the gate on every decision, so a corrupt lexicon must select the
            # same local fallback at startup instead of failing on the first
            # message.
            HeuristicRouter()
            return _build_clef_router(config)
        return HeuristicRouter()
    except LexiconError as exc:
        _LOGGER.critical(
            "Routing lexicon failed to load (%s); using a local-only fallback router",
            type(exc).__name__,
        )
        return LocalFallbackRouter()


def router_config_key(config: Any) -> tuple[Any, ...]:
    """Return a hashable snapshot of every setting ``build_router`` reads.

    Callers that cache a router use this instead of re-deriving the mode, the
    eligible Clef key, and the model settings in a second place.
    """
    return (
        str(_config_value(config, "ROUTER_MODE", "heuristic")).strip().lower(),
        _clef_api_key(config),
        _config_value(config, "ROUTER_CLEF_MODEL", DEFAULT_ROUTER_CLEF_MODEL),
        _config_value(config, "ROUTER_CLEF_THRESHOLD", DEFAULT_ROUTER_CLEF_THRESHOLD),
        _config_value(config, "ROUTER_CLEF_TIMEOUT_MS", DEFAULT_ROUTER_CLEF_TIMEOUT_MS),
    )


def _build_clef_router(config: Any) -> Router:
    api_key = _clef_api_key(config)
    if api_key is None:
        _warn_missing_clef_key_once()
        return HeuristicRouter()

    model = str(_config_value(config, "ROUTER_CLEF_MODEL", DEFAULT_ROUTER_CLEF_MODEL)).strip()
    if not model:
        _LOGGER.warning("ROUTER_CLEF_MODEL is empty; using %s", DEFAULT_ROUTER_CLEF_MODEL)
        model = DEFAULT_ROUTER_CLEF_MODEL

    return ClefRouter(
        api_key=api_key,
        model=model,
        threshold=_clef_threshold(config),
        timeout_s=_clef_timeout_s(config),
    )


def _clef_api_key(config: Any) -> str | None:
    """Return the only key eligible for Ollama Cloud's decision endpoint.

    The resolution order is the dedicated Clef key, an Ollama Cloud key from
    the environment, and finally the chat key only when its API URL is Ollama
    Cloud itself. A missing URL is not a default: a caller that supplies only a
    chat key cannot prove that key belongs to Ollama Cloud, so it is refused.
    A key issued by another provider is never sent to Ollama.
    """
    explicit = _first_config_or_env(config, ("ROUTER_CLEF_API_KEY",))
    if explicit is not None:
        return explicit

    ollama_key = os.environ.get("OLLAMA_API_KEY")
    if ollama_key is not None and ollama_key.strip():
        return ollama_key.strip()

    openai_key = _first_config_or_env(config, ("OPENAI_API_KEY",))
    if openai_key is None:
        return None
    openai_url = _config_value(config, "OPENAI_API_URL", None)
    if _is_ollama_cloud_url(openai_url):
        return openai_key
    return None


def _is_ollama_cloud_url(url: object) -> bool:
    """Return True only for a URL whose host is Ollama Cloud itself."""
    try:
        host = urlsplit(str(url)).hostname
    except ValueError:
        return False
    return host is not None and host.lower() == _OLLAMA_CLOUD_HOST


@lru_cache(maxsize=1)
def _warn_missing_clef_key_once() -> None:
    """Log the ineligible-key warning once per process."""
    _LOGGER.warning(
        "ROUTER_MODE=clef has no eligible key; set ROUTER_CLEF_API_KEY or OLLAMA_API_KEY, "
        "or use OPENAI_API_KEY with an Ollama Cloud OPENAI_API_URL; "
        "using the deterministic gate"
    )


def _clef_threshold(config: Any) -> float:
    raw = _config_value(config, "ROUTER_CLEF_THRESHOLD", DEFAULT_ROUTER_CLEF_THRESHOLD)
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_THRESHOLD %r; using %s",
            raw,
            DEFAULT_ROUTER_CLEF_THRESHOLD,
        )
        return DEFAULT_ROUTER_CLEF_THRESHOLD
    if not math.isfinite(threshold):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_THRESHOLD %r; using %s",
            raw,
            DEFAULT_ROUTER_CLEF_THRESHOLD,
        )
        return DEFAULT_ROUTER_CLEF_THRESHOLD
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
    raw = _config_value(config, "ROUTER_CLEF_TIMEOUT_MS", DEFAULT_ROUTER_CLEF_TIMEOUT_MS)
    try:
        timeout_ms = float(raw)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_TIMEOUT_MS %r; using %s",
            raw,
            DEFAULT_ROUTER_CLEF_TIMEOUT_MS,
        )
        return DEFAULT_ROUTER_CLEF_TIMEOUT_MS / 1000.0
    if not math.isfinite(timeout_ms) or timeout_ms <= 0.0:
        _LOGGER.warning(
            "Invalid ROUTER_CLEF_TIMEOUT_MS %r; using %s",
            raw,
            DEFAULT_ROUTER_CLEF_TIMEOUT_MS,
        )
        return DEFAULT_ROUTER_CLEF_TIMEOUT_MS / 1000.0
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
