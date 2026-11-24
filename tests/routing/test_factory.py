"""The package factory selects the heuristic and the optional Clef router."""

import logging

import pytest

from src.main import validate_critical_config
from src.routing import (
    ClefRouter,
    HeuristicRouter,
    LocalFallbackRouter,
    RouterInput,
    build_router,
)
from src.routing.heuristic import _bundled_lexicon
from src.routing.lexicon import LexiconError


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
    """A configured Ollama Cloud key selects the decision-model implementation."""
    router = build_router(
        {
            "ROUTER_MODE": "clef",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_API_URL": "https://ollama.com/v1/",
        }
    )

    assert isinstance(router, ClefRouter)
    assert router.router_id == "clef"


def _startup_config(mode: str) -> dict:
    return {
        "DISCORD_TOKEN": "test-token",
        "OPENAI_API_KEY": "sk-test",
        "RATE_LIMIT": 10,
        "RATE_LIMIT_PER": 60,
        "OUTPUT_TOKENS": 16384,
        "BOT_PRESENCE": "online",
        "ACTIVITY_TYPE": "watching",
        "ALLOWED_CHANNELS": ["general"],
        "ALLOWED_CHANNEL_IDS": [],
        "ROUTER_MODE": mode,
    }


def test_unknown_router_mode_fails_startup_validation() -> None:
    """A mistyped mode is a startup error, not an error reply on every message."""
    with pytest.raises(ValueError) as excinfo:
        validate_critical_config(_startup_config("gate"), logging.getLogger("test.router-mode"))

    assert "Unknown ROUTER_MODE 'gate'" in str(excinfo.value)


def test_retired_model_mode_keeps_its_explicit_startup_error() -> None:
    """The retired value keeps the message that points at Clef."""
    with pytest.raises(ValueError) as excinfo:
        validate_critical_config(_startup_config("model"), logging.getLogger("test.router-mode"))

    assert "ROUTER_MODE=model is not implemented; use ROUTER_MODE=clef" in str(excinfo.value)


@pytest.mark.parametrize(
    "contents",
    [None, b"{not valid json"],
    ids=["missing", "corrupt"],
)
def test_a_missing_or_corrupt_lexicon_injects_a_local_fallback(
    tmp_path,
    monkeypatch,
    caplog,
    contents,
) -> None:
    """Startup keeps the bot answering on the local route when the lexicon fails."""
    lexicon_path = tmp_path / "lexicon.en.json"
    if contents is not None:
        lexicon_path.write_bytes(contents)
    monkeypatch.setattr("src.routing.lexicon._BUNDLED_PATH", lexicon_path)
    _bundled_lexicon.cache_clear()

    try:
        with caplog.at_level(logging.CRITICAL, logger="src.routing"):
            try:
                router = build_router({"ROUTER_MODE": "heuristic"})
            except LexiconError as exc:
                msg = "build_router aborted startup instead of injecting a local router"
                raise AssertionError(msg) from exc

        assert isinstance(router, LocalFallbackRouter)
        decision = router.decide_sync(RouterInput(text="is it raining right now?"))
        assert decision.route == "local"
        assert decision.reasons == ("fallback:lexicon_error",)
        records = [
            record
            for record in caplog.records
            if record.levelno >= logging.CRITICAL and "lexicon" in record.getMessage()
        ]
        assert len(records) == 1
    finally:
        _bundled_lexicon.cache_clear()
