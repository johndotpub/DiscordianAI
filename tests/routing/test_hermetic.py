"""Routing works with sockets unavailable."""

from datetime import UTC, datetime
import socket

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)


def test_a_decision_succeeds_when_socket_creation_raises(monkeypatch) -> None:
    """No code on the decision path may open a socket."""

    def blocked_socket(*args, **kwargs):
        msg = "network access attempted during routing"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", blocked_socket)
    decision = HeuristicRouter().decide_sync(RouterInput(text="is github down", now=FIXED_NOW))

    assert decision.route == "web"
