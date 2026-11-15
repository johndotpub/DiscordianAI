"""The deterministic routing gate built from unweighted cues.

Overrides win over bearing cues, bearing cues win over follow-up inheritance,
and everything else is local. Reasons are short stable codes whose prefix
names the source that produced them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import Route, RouteDecision

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .features import Cue

_MAX_REASONS = 8
_WEB_OVERRIDE_SIGNALS = frozenset({"override.web_instruction", "override.url"})
_LOCAL_OVERRIDE_SIGNALS = frozenset({"override.local_instruction", "neg.supplied_artifact"})
_DIRECT_OVERRIDE_SIGNALS = frozenset(
    {"override.web_instruction", "override.url", "override.local_instruction"}
)


def decide(
    cues: Iterable[Cue],
    *,
    text: str = "",
    latency_ms: float = 0.0,
) -> RouteDecision:
    """Return the route implied by ``cues`` and the reasons that chose it."""
    ordered = sorted(cues, key=_sort_key)
    web_overrides = [cue for cue in ordered if cue.signal in _WEB_OVERRIDE_SIGNALS]
    if web_overrides:
        bearing = [cue for cue in ordered if cue.klass == "bearing"]
        return _decision("web", [*web_overrides, *bearing], text, latency_ms)

    local_overrides = [cue for cue in ordered if cue.signal in _LOCAL_OVERRIDE_SIGNALS]
    if local_overrides:
        return _decision("local", local_overrides, text, latency_ms)

    bearing = [cue for cue in ordered if cue.klass == "bearing"]
    if bearing:
        return _decision("web", bearing, text, latency_ms)

    inherited = [cue for cue in ordered if cue.source == "inherited"]
    if inherited:
        route: Route = "web" if inherited[0].detail == "web" else "local"
        return _decision(route, inherited, text, latency_ms)

    return RouteDecision(
        route="local",
        reasons=("local:default",),
        latency_ms=latency_ms,
        text=text,
    )


def _decision(
    route: Route,
    cues: Sequence[Cue],
    text: str,
    latency_ms: float,
) -> RouteDecision:
    reasons: list[str] = []
    for cue in cues:
        reason = _reason(cue)
        if reason not in reasons:
            reasons.append(reason)
        if len(reasons) == _MAX_REASONS:
            break
    return RouteDecision(
        route=route,
        reasons=tuple(reasons),
        latency_ms=latency_ms,
        text=text,
    )


def _reason(cue: Cue) -> str:
    if cue.source == "inherited":
        return f"inherited:{cue.detail}"
    if cue.signal in _DIRECT_OVERRIDE_SIGNALS:
        return f"override:{cue.signal.split('.', 1)[1]}"
    if cue.signal == "neg.supplied_artifact":
        return "local:supplied_artifact"
    if cue.klass == "bearing":
        return f"bearing:{cue.signal}"
    return f"gate:{cue.signal}"


def _sort_key(cue: Cue) -> tuple[int, int, str, str]:
    start = cue.span[0] if cue.span is not None else -1
    end = cue.span[1] if cue.span is not None else -1
    return (start, end, cue.signal, cue.detail)
