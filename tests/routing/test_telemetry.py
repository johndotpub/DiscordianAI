"""Routing telemetry never carries message or matched-term content."""

from datetime import UTC, datetime

import pytest

from src.routing.contracts import RouteDecision, RouterInput
from src.routing.heuristic import HeuristicRouter
from src.routing.telemetry import decision_log_fields
from src.smart_orchestrator import _routing_metadata

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
UNIQUE_MARKER = "zqxwcevunique9317"


def _decision(text: str) -> RouteDecision:
    return HeuristicRouter().decide_sync(RouterInput(text=text, now=FIXED_NOW))


def test_a_unique_message_token_leaves_no_trace_in_telemetry() -> None:
    """The log fields contain reason codes, never the message or a matched term."""
    fields = decision_log_fields(_decision(f"is github down {UNIQUE_MARKER}"))

    rendered = repr(fields)
    assert UNIQUE_MARKER not in rendered
    assert "down" not in rendered


def test_telemetry_has_the_required_content_free_fields() -> None:
    """Every documented field is present and reasons stay capped."""
    fields = decision_log_fields(_decision("is github down"))

    assert set(fields) == {"route", "service", "router_id", "reasons", "latency_ms"}
    assert fields["service"] == "perplexity"
    assert fields["router_id"] == "gate"
    assert fields["reasons"] == "bearing:pred.status"
    assert isinstance(fields["latency_ms"], float)


@pytest.mark.parametrize(
    ("route", "service"),
    [("web", "perplexity"), ("local", "openai")],
)
def test_routing_metadata_uses_the_decision_router_identity(route: str, service: str) -> None:
    """A Clef decision keeps its own cache identity instead of the gate's."""
    decision = RouteDecision(
        route=route,
        reasons=("clef:x:p=0.900",),
        router_id="clef",
        policy_version="1",
    )

    metadata = _routing_metadata(decision, service)

    assert metadata.router_id == "clef"
    assert metadata.policy_version == "1"
    assert metadata.salt == f"{route}:clef:1"


def test_routing_metadata_defaults_to_the_gate() -> None:
    """A decision built without an identity keeps the gate's identity."""
    decision = RouteDecision(route="local", reasons=("local:default",))

    metadata = _routing_metadata(decision, "openai")

    assert metadata.router_id == "gate"
    assert metadata.policy_version == "1"
    assert metadata.salt == "local:gate:1"
