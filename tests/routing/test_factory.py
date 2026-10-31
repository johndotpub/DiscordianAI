"""The package factory selects the heuristic and refuses the missing model."""

import pytest

from src.routing import HeuristicRouter, build_router


def test_build_router_defaults_to_the_heuristic() -> None:
    """No config and an explicit heuristic config both build the heuristic."""
    assert isinstance(build_router(None), HeuristicRouter)
    assert isinstance(build_router({"ROUTER_MODE": "heuristic"}), HeuristicRouter)


def test_model_mode_names_the_design_document() -> None:
    """The unimplemented model seam fails loudly and points at its design."""
    with pytest.raises(NotImplementedError) as excinfo:
        build_router({"ROUTER_MODE": "model"})

    assert "docs/routing/DESIGN.md" in str(excinfo.value)


def test_unknown_mode_is_rejected() -> None:
    """A typo in ROUTER_MODE does not silently pick a router."""
    with pytest.raises(ValueError) as excinfo:
        build_router({"ROUTER_MODE": "magic"})

    assert "magic" in str(excinfo.value)


def test_environment_mode_is_honoured_when_config_omits_it(monkeypatch) -> None:
    """ROUTER_MODE=model in the environment reaches the same refusal."""
    monkeypatch.setenv("ROUTER_MODE", "model")

    with pytest.raises(NotImplementedError) as excinfo:
        build_router(None)

    assert "docs/routing/DESIGN.md" in str(excinfo.value)
