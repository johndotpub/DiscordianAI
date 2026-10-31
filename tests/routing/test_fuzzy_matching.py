"""Regression tests for edit-type typo matching."""

from datetime import UTC, datetime

import pytest

from src.routing.contracts import RouterInput
from src.routing.heuristic import HeuristicRouter
from src.routing.lexicon import Lexicon

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
LEXICON = Lexicon.load()
ROUTER = HeuristicRouter()
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _decide(text: str):
    return ROUTER.decide_sync(RouterInput(text=text, now=FIXED_NOW))


def _single_word_terms():
    return sorted(
        (term for terms in LEXICON.terms.values() for term in terms if " " not in term.text),
        key=lambda term: (term.text, term.class_name),
    )


def _substitution_variants(word: str) -> list[str]:
    variants: set[str] = set()
    for index, original in enumerate(word):
        for letter in ALPHABET:
            if letter != original:
                variants.add(word[:index] + letter + word[index + 1 :])
    variants.discard(word)
    return sorted(variants)


def test_a_definition_question_is_not_rewritten_into_a_rate_lookup() -> None:
    """race is not a typo for rate in a question about race conditions."""
    decision = _decide("explain what a race condition is in two sentences")

    assert decision.route == "local"
    assert not any(
        item.signal == "topic.volatile" and item.detail == "rate" for item in decision.evidence
    )


def test_a_plain_definition_question_stays_local() -> None:
    """The definitional form also stays local without the imperative frame."""
    assert _decide("what is a race condition").route == "local"


@pytest.mark.parametrize("text", ["is github down", "is github dwon"])
def test_status_questions_still_route_to_web_with_or_without_a_transposition(text: str) -> None:
    """A transposed status predicate still reaches the web."""
    assert _decide(text).route == "web"


def test_a_short_transposition_hits_its_lexicon_term() -> None:
    """dwon is a transposition of down, not a different word."""
    assert any(term.text == "down" for term in LEXICON.fuzzy_matches("dwon"))


def test_an_insertion_still_matches_its_lexicon_term() -> None:
    """An extra character is a typo shape, not a substitution."""
    assert any(term.text == "weather" for term in LEXICON.fuzzy_matches("wether"))
    assert any(term.text == "degraded" for term in LEXICON.fuzzy_matches("degradded"))


def test_a_deletion_still_matches_its_lexicon_term() -> None:
    """offlin is a deletion from offline."""
    assert any(term.text == "offline" for term in LEXICON.fuzzy_matches("offlin"))


def test_a_typo_in_a_volatile_topic_still_routes_to_web() -> None:
    """A six-character insertion typo still hits the weather topic."""
    decision = _decide("what's the wether in london")

    assert decision.route == "web"
    assert any(
        item.signal == "topic.volatile" and item.detail == "weather" for item in decision.evidence
    )


def test_a_transposed_version_typo_still_routes_to_web() -> None:
    """verison is a transposition of version."""
    decision = _decide("wat is the latest verison of postgres")

    assert decision.route == "web"
    assert any(
        item.signal == "topic.version_currency" and item.detail == "version"
        for item in decision.evidence
    )


def test_a_deletion_still_routes_to_web() -> None:
    """offlin is a deletion of offline in a status question."""
    decision = _decide("is the api offlin")

    assert decision.route == "web"
    assert any(
        item.signal == "pred.status" and item.detail == "offline" for item in decision.evidence
    )


def test_short_function_words_are_never_fuzzy_matched() -> None:
    """on and to are prepositions, not deletions from won and cto."""
    assert LEXICON.fuzzy_matches("on") == ()
    assert LEXICON.fuzzy_matches("to") == ()


def test_tokens_shorter_than_four_characters_are_not_fuzzy_matched() -> None:
    """A three-letter token has too many one-edit neighbours to be reliable."""
    assert LEXICON.fuzzy_matches("dwn") == ()
    assert not any(hit.fuzzy for hit in LEXICON.find("dwn"))


@pytest.mark.parametrize(
    "term",
    _single_word_terms(),
    ids=lambda term: f"{term.class_name}:{term.text}",
)
def test_no_term_is_reachable_from_a_same_length_substitution(term) -> None:
    """A single substitution is a different word, never a typo of this term."""
    for variant in _substitution_variants(term.text):
        assert term not in LEXICON.fuzzy_matches(variant), variant
