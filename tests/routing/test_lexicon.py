"""Tests for lexicon loading, validation, and fuzzy hits."""

import json
from pathlib import Path

import pytest

from src.routing.lexicon import Lexicon, LexiconError

STARTER_CLASS_COUNT = 12
STARTER_TERM_COUNT = 154


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    """Write a lexicon document and return its path."""
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _document() -> dict[str, object]:
    """Return a minimal valid lexicon document."""
    return {
        "version": "1",
        "language": "en",
        "classes": {
            "volatile_topic": {
                "klass": "bearing",
                "weight": 1.8,
                "terms": ["weather", "news"],
            },
            "greeting": {
                "klass": "framing",
                "weight": -1.5,
                "terms": ["hello"],
            },
        },
        "overrides": {"web_instruction": ["search the web"]},
    }


def test_bundled_lexicon_loads_with_class_weights() -> None:
    """The bundled lexicon exposes every class and a class-level weight."""
    lexicon = Lexicon.load()

    assert lexicon.version == "1"
    assert lexicon.language == "en"
    assert len(lexicon.classes) == STARTER_CLASS_COUNT
    assert sum(len(terms) for terms in lexicon.terms.values()) == STARTER_TERM_COUNT
    assert lexicon.class_weights["volatile_topic"] == 1.8
    assert lexicon.classes["social_only"] == "framing"
    assert lexicon.find("weather")


def test_delete_one_index_finds_a_typo_in_every_class() -> None:
    """A token one edit from a term hits that term's class."""
    lexicon = Lexicon.load()

    weather_hits = lexicon.find("wether")
    offline_hits = lexicon.find("offlin")

    assert any(
        hit.term.text == "weather" and hit.term.class_name == "volatile_topic"
        for hit in weather_hits
    )
    assert any(
        hit.term.text == "offline" and hit.term.class_name == "state_adjective"
        for hit in offline_hits
    )
    assert all(hit.fuzzy for hit in weather_hits if hit.term.text == "weather")


def test_unknown_evidence_class_names_the_bad_class(tmp_path: Path) -> None:
    """An unknown klass raises with both the class name and the bad value."""
    document = _document()
    classes = document["classes"]
    assert isinstance(classes, dict)
    classes["bad_class"] = {
        "klass": "mystery",
        "weight": 1.0,
        "terms": ["thing"],
    }
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "bad_class" in message
    assert "mystery" in message


def test_weight_outside_range_names_the_class(tmp_path: Path) -> None:
    """A weight outside [-10, 10] raises and names the offending class."""
    document = _document()
    classes = document["classes"]
    assert isinstance(classes, dict)
    topic = classes["volatile_topic"]
    assert isinstance(topic, dict)
    topic["weight"] = 10.5
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "volatile_topic" in message
    assert "weight" in message


def test_term_in_two_classes_names_the_term_and_both_classes(tmp_path: Path) -> None:
    """A shared term raises and names the term and both owning classes."""
    document = _document()
    classes = document["classes"]
    assert isinstance(classes, dict)
    classes["second_topic"] = {
        "klass": "bearing",
        "weight": 1.0,
        "terms": ["weather"],
    }
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "weather" in message
    assert "volatile_topic" in message
    assert "second_topic" in message


def test_uncompilable_override_names_the_override_group(tmp_path: Path) -> None:
    """An invalid override regex raises and names the override group."""
    document = _document()
    document["overrides"] = {"web_instruction": ["("]}
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "web_instruction" in message
    assert "regex" in message


def test_version_mismatch_names_version(tmp_path: Path) -> None:
    """An unsupported version raises and names the version key."""
    document = _document()
    document["version"] = "2"
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "version" in message
    assert "'2'" in message


def test_language_mismatch_names_language(tmp_path: Path) -> None:
    """A non-English lexicon is rejected by name."""
    document = _document()
    document["language"] = "fr"
    path = _write(tmp_path, document)

    with pytest.raises(LexiconError) as excinfo:
        Lexicon.load(path)

    message = str(excinfo.value)
    assert "language" in message
    assert "'fr'" in message
