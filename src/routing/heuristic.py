"""The deterministic, network-free heuristic router."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from functools import lru_cache
import re
from time import perf_counter
from typing import TYPE_CHECKING

from .contracts import (
    ConversationContext,
    EvidenceClass,
    RouteDecision,
    RouterConfig,
    RouterInput,
)
from .features import (
    Cue,
    TextViews,
    extract_cues,
    extract_overrides,
    parse_explicit_route,
    views,
)
from .lexicon import Lexicon
from .scoring import decide

if TYPE_CHECKING:
    from collections.abc import Callable

_FOLLOW_UP_MAX_TOKENS = 6
_INHERIT_WEIGHT = 2.0
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_TITLE_CASE_PATTERN = re.compile(r"\b[A-Z][a-z]+")
_ANAPHORS = frozenset(
    {
        "again",
        "it",
        "more",
        "one",
        "ones",
        "same",
        "that",
        "them",
        "these",
        "they",
        "this",
        "those",
    }
)
_BARE_CONTINUATIONS = (
    "tell me more",
    "more detail",
    "more details",
    "go on",
    "keep going",
    "continue",
    "what about",
    "how about",
    "and then",
    "what else",
    "anything else",
    "same thing",
)
_COORDINATORS = frozenset({"also", "and", "but", "or", "plus", "so", "then"})
_CONTINUATION_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "anything",
        "continue",
        "detail",
        "details",
        "do",
        "else",
        "first",
        "go",
        "how",
        "instead",
        "keep",
        "me",
        "more",
        "on",
        "one",
        "ones",
        "please",
        "second",
        "tell",
        "the",
        "then",
        "thing",
        "what",
        "why",
    }
)


@lru_cache(maxsize=1)
def _bundled_lexicon() -> Lexicon:
    return Lexicon.load()


class HeuristicRouter:
    """Score cues with a fixed pipeline and no I/O, model, or clock reads."""

    router_id = "heuristic@1"
    policy_version = "1"

    def __init__(
        self,
        *,
        config: RouterConfig | None = None,
        lexicon: Lexicon | None = None,
    ) -> None:
        """Create a heuristic router with optional thresholds and lexicon."""
        self.config = config or RouterConfig(
            router_id=self.router_id,
            policy_version=self.policy_version,
        )
        self._lexicon = lexicon or _bundled_lexicon()

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision for ``request``."""
        return self.decide_sync(request)

    def decide_sync(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision synchronously for tests and the corpus runner."""
        started = perf_counter()
        explicit, text = parse_explicit_route(request.text)
        text_views = views(text)
        cues: list[Cue] = [
            *extract_overrides(text_views, self._lexicon),
            *extract_cues(text_views, self._lexicon, clock=_clock(request.now)),
        ]
        if explicit is not None:
            cues.append(
                Cue(
                    signal=f"override.route.{explicit.route}",
                    klass="override",
                    span=(0, 0),
                    detail=explicit.class_hint or explicit.route,
                    source="override",
                    weight=1.0,
                )
            )
        else:
            inherited = _inheritance_cue(request, text_views, cues)
            if inherited is not None:
                cues.append(inherited)
        latency_ms = (perf_counter() - started) * 1000.0
        return decide(
            cues,
            self._effective_config(request.config),
            text=text,
            latency_ms=latency_ms,
        )

    def _effective_config(self, request_config: RouterConfig) -> RouterConfig:
        config = self.config if request_config == RouterConfig() else request_config
        return replace(
            config,
            router_id=self.router_id,
            policy_version=self.policy_version,
        )


def _clock(now: datetime | date) -> Callable[[], date]:
    if isinstance(now, datetime):
        return now.date
    return lambda: now


def _inheritance_cue(
    request: RouterInput,
    text_views: TextViews,
    cues: list[Cue],
) -> Cue | None:
    tokens = _TOKEN_PATTERN.findall(text_views.folded)
    if len(tokens) > _FOLLOW_UP_MAX_TOKENS:
        return None
    if not _is_follow_up(tokens, text_views.folded):
        return None
    if any(cue.klass == "bearing" for cue in cues):
        return None
    last_route = request.context.last_route
    if last_route is None or not _assistant_recent(request.context):
        return None
    if _topic_shift(text_views, tokens, request.context):
        return None

    klass: EvidenceClass = "override" if last_route == "web" else "local"
    weight = _INHERIT_WEIGHT if last_route == "web" else -_INHERIT_WEIGHT
    return Cue(
        signal=f"inherit.{last_route}",
        klass=klass,
        span=None,
        detail=last_route,
        source="inherited",
        weight=weight,
    )


def _is_follow_up(tokens: list[str], folded: str) -> bool:
    if not tokens:
        return False
    if tokens[0] in _COORDINATORS:
        return True
    if any(token in _ANAPHORS for token in tokens):
        return True
    return any(phrase in folded for phrase in _BARE_CONTINUATIONS)


def _assistant_recent(context: ConversationContext) -> bool:
    if not context.turns:
        return context.last_route is not None
    for gap, turn in enumerate(reversed(context.turns)):
        if turn.role == "assistant":
            return gap <= 1
    return False


def _topic_shift(
    text_views: TextViews,
    tokens: list[str],
    context: ConversationContext,
) -> bool:
    prior_terms = {
        token
        for turn in context.turns
        if turn.role == "user"
        for token in _TOKEN_PATTERN.findall(turn.text.lower())
    }
    if any(
        match.group().lower() not in prior_terms
        for match in _TITLE_CASE_PATTERN.finditer(text_views.surface)
    ):
        return True
    content = {
        token
        for token in tokens
        if token not in _CONTINUATION_STOPWORDS and token not in _ANAPHORS
    }
    return bool(content - prior_terms)
