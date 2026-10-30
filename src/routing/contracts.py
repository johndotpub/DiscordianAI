"""Frozen contracts shared by every routing implementation."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol

Route = Literal["web", "local"]
Band = Literal["confident", "unsure"]
EvidenceClass = Literal["override", "bearing", "framing", "local"]
Source = Literal["structural", "lexicon", "override", "inherited"]
Role = Literal["user", "assistant"]
ChannelKind = Literal["channel", "announcement", "dm"]


@dataclass(frozen=True, slots=True)
class Turn:
    """One message in a conversation, with the route used for assistant turns."""

    role: Role
    text: str
    route: Route | None = None


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """Prior conversation state available to a router."""

    turns: tuple[Turn, ...] = ()
    last_route: Route | None = None
    channel_kind: ChannelKind = "channel"


@dataclass(frozen=True, slots=True)
class RouterConfig:
    """Tunable thresholds and policy identifiers for one router."""

    router_id: str = "heuristic@1"
    policy_version: str = "1"
    tau: float = 0.5
    tau_local: float = 0.25
    t_mid: float = 0.0
    temperature: float = 0.6
    lambda_framing: float = 0.35
    cache_ttl_seconds: int = 300


@dataclass(frozen=True, slots=True)
class RouterInput:
    """The complete input for one routing decision."""

    text: str
    context: ConversationContext = field(default_factory=ConversationContext)
    config: RouterConfig = field(default_factory=RouterConfig)
    request_id: str = ""
    now: datetime | date = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Evidence:
    """One signed contribution to a routing score."""

    signal: str
    klass: EvidenceClass
    weight: float
    span: tuple[int, int] | None
    detail: str
    source: Source = "structural"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """How a caller may cache the answer produced under this decision."""

    cacheable: bool
    ttl_seconds: int
    salt: str


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """The route, its confidence, and the trace that produced it."""

    route: Route
    band: Band
    confidence: float
    score: float
    threshold: float
    evidence: tuple[Evidence, ...]
    cache: CachePolicy
    router_id: str
    policy_version: str
    latency_ms: float
    text: str = ""
    source: Source = "structural"


class Router(Protocol):
    """Structural interface shared by the heuristic and model routers."""

    router_id: str
    policy_version: str

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision for ``request``."""
        ...
