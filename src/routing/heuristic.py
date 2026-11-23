"""The deterministic, network-free heuristic router."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
import re
from time import perf_counter
from typing import TYPE_CHECKING

from .features import (
    Cue,
    TextViews,
    extract_cues,
    extract_overrides,
    mask_code,
    views,
)
from .gate import decide
from .lexicon import Lexicon
from .text import TOKEN_PATTERN

if TYPE_CHECKING:
    from collections.abc import Callable

    from .contracts import (
        ConversationContext,
        EvidenceClass,
        RouteDecision,
        RouterInput,
    )

_FOLLOW_UP_MAX_TOKENS = 6
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
    """Apply the deterministic gate with no I/O, model, or clock reads."""

    router_id = "gate"
    policy_version = "1"

    def __init__(self, *, lexicon: Lexicon | None = None) -> None:
        """Create a heuristic router with an optional lexicon."""
        self._lexicon = lexicon or _bundled_lexicon()

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision for ``request``."""
        return self.decide_sync(request)

    def decide_sync(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision synchronously for tests and the corpus runner."""
        started = perf_counter()
        text_views = views(request.text)
        masked_views = views(mask_code(request.text))
        cues: list[Cue] = [
            *extract_overrides(masked_views, self._lexicon),
            *extract_cues(text_views, self._lexicon, clock=_clock(request.now)),
        ]
        inherited = _inheritance_cue(request, text_views, cues)
        if inherited is not None:
            cues.append(inherited)
        latency_ms = (perf_counter() - started) * 1000.0
        return decide(cues, text=request.text, latency_ms=latency_ms)


def _clock(now: datetime | date) -> Callable[[], date]:
    if isinstance(now, datetime):
        return now.date
    return lambda: now


def _inheritance_cue(
    request: RouterInput,
    text_views: TextViews,
    cues: list[Cue],
) -> Cue | None:
    tokens = TOKEN_PATTERN.findall(text_views.folded)
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
    return Cue(
        signal=f"inherit.{last_route}",
        klass=klass,
        span=None,
        detail=last_route,
        source="inherited",
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
        for token in TOKEN_PATTERN.findall(turn.text.lower())
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
