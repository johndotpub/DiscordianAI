"""Weighted scoring and the routing decision built from a cue trace."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import TYPE_CHECKING

from .contracts import CachePolicy, Evidence, RouteDecision, RouterConfig, Source

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .features import Cue

STRUCTURAL_WEIGHTS: dict[str, float] = {
    "pred.event": 2.2,
    "pred.error_code": 2.0,
    "shape.version": 2.0,
    "shape.money": 1.8,
    "time.year": 2.0,
    "time.deixis": 1.4,
    "time.deixis.framing": 1.0,
    "frame.question": 1.0,
    "frame.imperative": 0.8,
    "frame.opinion": 0.4,
    "frame.creative": 0.4,
    "frame.procedural": 0.5,
    "cue.lookup": 0.6,
    "ref.entity": 0.8,
    "neg.narrative": -2.0,
    "neg.supplied_artifact": -4.0,
    "code.shape": -3.0,
}
"""Base weight for every structural signal emitted by ``features``."""

_EXPLICIT_WEB_SIGNALS = frozenset({"override.route.web"})
_EXPLICIT_LOCAL_SIGNALS = frozenset({"override.route.local"})
_WEB_OVERRIDE_SIGNALS = frozenset({"override.web_instruction", "override.url"})
_LOCAL_OVERRIDE_SIGNALS = frozenset({"override.local_instruction", "neg.supplied_artifact"})
_MENTION_PATTERN = re.compile(r"<@[!&]?\d+>|<#\d+>|<a?:[A-Za-z0-9_]+:\d+>")


@dataclass(frozen=True, slots=True)
class Score:
    """The weighted trace, its probability, and the facts the gate needs."""

    value: float
    p_web: float
    evidence: tuple[Evidence, ...]
    has_bearing: bool
    has_web_override: bool
    has_local_override: bool
    has_url_override: bool
    has_explicit_web: bool = False
    has_explicit_local: bool = False

    @property
    def has_override(self) -> bool:
        """Return True when any override cue is present, including inherited ones."""
        return any(item.klass == "override" for item in self.evidence)


def score(cues: Iterable[Cue], config: RouterConfig) -> Score:
    """Apply family saturation and ``lambda_framing`` to ``cues``.

    Within one family the strongest hit keeps its full weight, the second hit
    keeps half, and every later hit is ignored. The returned evidence weights
    are the applied weights, so ``sum(evidence.weight)`` equals ``value``.
    """
    families: dict[str, list[Cue]] = {}
    for cue in cues:
        families.setdefault(cue.signal, []).append(cue)

    applied: list[Evidence] = []
    for signal in sorted(families):
        hits = sorted(
            families[signal],
            key=lambda cue: (
                -abs(cue.weight),
                cue.span[0] if cue.span is not None else -1,
                cue.span[1] if cue.span is not None else -1,
                cue.detail,
            ),
        )
        for rank, cue in enumerate(hits[:2]):
            weight = cue.weight if rank == 0 else cue.weight * 0.5
            if cue.klass == "framing":
                weight *= config.lambda_framing
            applied.append(
                Evidence(
                    signal=cue.signal,
                    klass=cue.klass,
                    weight=weight,
                    span=cue.span,
                    detail=cue.detail,
                    source=cue.source,
                )
            )

    value = sum(item.weight for item in applied)
    probability = _sigmoid((value - config.t_mid) / max(config.temperature, 1e-9))
    return Score(
        value=value,
        p_web=probability,
        evidence=tuple(applied),
        has_bearing=any(item.klass == "bearing" for item in applied),
        has_web_override=any(item.signal in _WEB_OVERRIDE_SIGNALS for item in applied),
        has_local_override=any(item.signal in _LOCAL_OVERRIDE_SIGNALS for item in applied),
        has_url_override=any(item.signal == "override.url" for item in applied),
        has_explicit_web=any(item.signal in _EXPLICIT_WEB_SIGNALS for item in applied),
        has_explicit_local=any(item.signal in _EXPLICIT_LOCAL_SIGNALS for item in applied),
    )


def decide(
    cues: Iterable[Cue],
    config: RouterConfig,
    *,
    text: str = "",
    latency_ms: float = 0.0,
) -> RouteDecision:
    """Turn cues into a route, band, confidence, evidence trace, and cache policy."""
    scored = score(cues, config)
    resolved_router_id = config.router_id
    resolved_policy_version = config.policy_version
    decision_source: Source = (
        "override" if scored.has_explicit_web or scored.has_explicit_local else "structural"
    )

    if scored.has_explicit_local:
        route, band, threshold, confidence = "local", "confident", config.tau_local, 1.0
    elif scored.has_explicit_web:
        route, band, threshold, confidence = "web", "confident", config.tau, 1.0
    elif scored.has_local_override:
        route, band, threshold, confidence = "local", "confident", config.tau_local, 1.0
    elif scored.has_web_override:
        route, band, threshold, confidence = "web", "confident", config.tau, 1.0
    elif not scored.has_bearing and not scored.has_override:
        route, band, threshold, confidence = "local", "confident", config.tau_local, 1.0
    elif scored.p_web >= config.tau:
        route, band, threshold, confidence = (
            "web",
            "confident",
            config.tau,
            scored.p_web,
        )
    elif scored.p_web <= config.tau_local:
        route, band, threshold, confidence = (
            "local",
            "confident",
            config.tau_local,
            1.0 - scored.p_web,
        )
    else:
        route, band, threshold, confidence = (
            "local",
            "unsure",
            config.tau,
            1.0 - scored.p_web,
        )

    cacheable = (
        band == "confident"
        and _has_content(text)
        and not scored.has_url_override
        and not scored.has_explicit_web
        and not scored.has_explicit_local
        and not (route == "local" and scored.has_bearing)
    )
    cache = CachePolicy(
        cacheable=cacheable,
        ttl_seconds=config.cache_ttl_seconds,
        salt=f"{route}:{resolved_router_id}:{resolved_policy_version}",
    )
    return RouteDecision(
        route=route,
        band=band,
        confidence=confidence,
        score=scored.value,
        threshold=threshold,
        evidence=scored.evidence,
        cache=cache,
        router_id=resolved_router_id,
        policy_version=resolved_policy_version,
        latency_ms=latency_ms,
        text=text,
        source=decision_source,
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _has_content(text: str) -> bool:
    return any(character.isalnum() for character in _MENTION_PATTERN.sub("", text))
