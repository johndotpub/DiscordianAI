"""The package factory selects the heuristic and the optional Clef router."""

import pytest

from src.routing import ClefRouter, HeuristicRouter, build_router


def test_build_router_defaults_to_the_heuristic() -> None:
    """No config and an explicit heuristic config both build the heuristic."""
    assert isinstance(build_router(None), HeuristicRouter)
    assert isinstance(build_router({"ROUTER_MODE": "heuristic"}), HeuristicRouter)


def test_model_mode_names_the_replacement() -> None:
    """The retired model alias fails loudly and points at Clef."""
    with pytest.raises(NotImplementedError) as excinfo:
        build_router({"ROUTER_MODE": "model"})

    assert "use ROUTER_MODE=clef" in str(excinfo.value)


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

    assert "use ROUTER_MODE=clef" in str(excinfo.value)


def test_clef_mode_without_a_key_falls_back_to_the_heuristic(monkeypatch) -> None:
    """Clef never turns a missing key into a startup failure."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    assert isinstance(build_router({"ROUTER_MODE": "clef"}), HeuristicRouter)


def test_clef_mode_with_a_key_builds_the_clef_router() -> None:
    """A configured key selects the decision-model implementation."""
    router = build_router({"ROUTER_MODE": "clef", "OPENAI_API_KEY": "test-key"})

    assert isinstance(router, ClefRouter)
    assert router.router_id == "clef"
