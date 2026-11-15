"""Frozen contracts shared by every routing implementation."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol

Route = Literal["web", "local"]
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
class RouterInput:
    """The complete input for one routing decision."""

    text: str
    context: ConversationContext = field(default_factory=ConversationContext)
    request_id: str = ""
    now: datetime | date = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """The chosen route and the stable reason codes that produced it."""

    route: Route
    reasons: tuple[str, ...] = ()
    latency_ms: float = 0.0
    text: str = ""
    router_id: str = "gate"
    policy_version: str = "1"


class Router(Protocol):
    """Structural interface shared by the heuristic and model routers."""

    router_id: str
    policy_version: str

    async def decide(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision for ``request``."""

    def decide_sync(self, request: RouterInput) -> RouteDecision:
        """Return the routing decision synchronously for tests and offline runs."""
