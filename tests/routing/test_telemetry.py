"""Routing telemetry never carries message or matched-term content."""

from datetime import UTC, datetime

from src.routing.contracts import RouteDecision, RouterInput
from src.routing.heuristic import HeuristicRouter
from src.routing.telemetry import decision_log_fields

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
UNIQUE_MARKER = "zqxwcevunique9317"


def _decision(text: str) -> RouteDecision:
    return HeuristicRouter().decide_sync(RouterInput(text=text, now=FIXED_NOW))


def test_a_unique_message_token_leaves_no_trace_in_telemetry() -> None:
    """The log fields contain signal ids, never the message or a matched term."""
    fields = decision_log_fields(_decision(f"is github down {UNIQUE_MARKER}"))

    rendered = repr(fields)
    assert UNIQUE_MARKER not in rendered
    assert "down" not in rendered


def test_telemetry_has_the_required_content_free_fields() -> None:
    """Every documented field is present and reasons stay capped."""
    fields = decision_log_fields(_decision("is github down"))

    assert set(fields) == {
        "route",
        "band",
        "service",
        "score",
        "threshold",
        "reasons",
        "router_id",
        "policy_version",
        "latency_ms",
    }
    assert fields["service"] == "perplexity"
    assert len(fields["reasons"]) <= 5
    assert all(isinstance(reason, str) for reason in fields["reasons"])
