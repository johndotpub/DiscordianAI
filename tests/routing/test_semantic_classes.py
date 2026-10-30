"""Regression cases drawn from the blind routing sets.

The blind sets are development data now: each row below is a message that was
misrouted before the class or negation fix it exercises.
"""

from datetime import UTC, datetime

import pytest

from src.routing.contracts import ConversationContext, RouterInput
from src.routing.features import extract_cues, extract_overrides, views
from src.routing.heuristic import HeuristicRouter
from src.routing.lexicon import Lexicon

FIXED_NOW = datetime(2026, 10, 30, tzinfo=UTC)
LEXICON = Lexicon.load()
ROUTER = HeuristicRouter()

NEW_CLASS_CORE_TERMS = {
    "release_state": {
        "out yet",
        "come out",
        "comes out",
        "release candidate",
        "early access",
        "general availability",
        "deprecated",
        "sunset",
    },
    "commerce": {
        "how much",
        "pricing",
        "price",
        "cost",
        "trading at",
        "going for",
        "tickets",
        "msrp",
        "per month",
        "in stock",
        "restock",
        "sold out",
    },
    "incumbency": {
        "president",
        "prime minister",
        "pm",
        "ceo",
        "cto",
        "senator",
        "governor",
        "mayor",
        "chancellor",
        "manager",
        "coach",
        "in office",
        "these days",
    },
    "version_currency": {
        "version",
        "lts",
        "kernel",
        "release",
        "releases",
        "edition",
        "changelog",
        "release notes",
        "roadmap",
        "deprecation",
    },
}
NEW_CLASS_WEIGHTS = {
    "release_state": 2.2,
    "commerce": 2.0,
    "incumbency": 1.6,
    "version_currency": 1.8,
}
SEMANTIC_CASES = [
    ("is the new season of severance out yet?", "web", "pred.release"),
    ("did rust 1.85 ship yet?", "web", "pred.release"),
    ("how much is spotify premium a month?", "web", "topic.commerce"),
    ("what's a gallon of milk going for in the us?", "web", "topic.commerce"),
    ("how much is a dozen eggs these days?", "web", "topic.commerce"),
    ("are there tickets left for the concert on saturday?", "web", "topic.commerce"),
    ("who manages man united?", "web", "topic.incumbency"),
    ("who's running apple these days?", "web", "topic.incumbency"),
    ("who is the ceo of openai right now?", "web", "topic.incumbency"),
    ("whats the newest lts ubuntu?", "web", "topic.version_currency"),
    ("what's in the latest postgres release?", "web", "topic.version_currency"),
    ("the president of the company", "local", ""),
]
SUPPLIED_ARTEFACT_CASES = [
    "summarize:\nThe deploy failed because the migration ran before the schema applied.",
    "summarise:\nThe deploy failed because the migration ran before the schema applied.",
    "summarise these standup notes:\nparser shipped, two leaks fixed, auth blocked on vendor.",
    "tl;dr this:\nThe report found remote work raised productivity in software teams.",
    "turn these notes into a paragraph:\n- shipped parser\n- fixed two leaks",
    "turn this into a haiku:\nthe deploy failed at midnight",
    "these notes say the build failed on the release branch",
    "this log shows an upstream timeout after thirty seconds",
    "this error means the migration ran before the schema applied",
    "this json has a trailing comma",
    "this changelog mentions a breaking release",
    "this paragraph needs a shorter version",
    "what's this saying?\nPursuant to section 4.2, either party may terminate.",
    'explain in plain english: "Pursuant to section 4.2, either party may terminate."',
    "should the migration run before the schema be applied?",
    "in our schema the field is optional",
]
NATURAL_LANGUAGE_INSTRUCTION_CASES = [
    ("search the web for the rust edition guide", "web", "override.web_instruction"),
    ("look it up online", "web", "override.web_instruction"),
    ("answer from memory", "local", "override.local_instruction"),
    ("do not search", "local", "override.local_instruction"),
]


def _decide(text: str):
    return ROUTER.decide_sync(RouterInput(text=text, context=ConversationContext(), now=FIXED_NOW))


def test_each_new_bearing_class_is_in_the_lexicon_with_its_core_terms() -> None:
    """The JSON owns the class, its weight, and its vocabulary."""
    for name, expected_terms in NEW_CLASS_CORE_TERMS.items():
        assert name in LEXICON.classes
        assert LEXICON.classes[name] == "bearing"
        assert LEXICON.class_weights[name] == pytest.approx(NEW_CLASS_WEIGHTS[name])
        actual_terms = {term.text for term in LEXICON.terms[name]}
        assert expected_terms <= actual_terms
        assert len(actual_terms) <= 25


@pytest.mark.parametrize(("text", "expected_route", "signal"), SEMANTIC_CASES)
def test_semantic_failure_classes_change_the_decision(
    text: str, expected_route: str, signal: str
) -> None:
    """A blind-set message routes by the class named in the case table."""
    decision = _decide(text)

    assert decision.route == expected_route
    if signal:
        assert any(item.signal == signal for item in decision.evidence)


def test_change_class_requires_a_change_of_state() -> None:
    """Bare change and changes are not change events; changed still is."""
    assert not any(hit.term.class_name == "change_verb" for hit in LEXICON.find("change"))
    assert not any(hit.term.class_name == "change_verb" for hit in LEXICON.find("changes"))
    assert any(hit.term.text == "changed" for hit in LEXICON.find("changed"))

    local = _decide("how do i undo the last commit but keep the changes?")
    web = _decide("what changed in the newest ios update?")

    assert local.route == "local"
    assert not any(item.signal == "pred.change" for item in local.evidence)
    assert web.route == "web"
    assert any(item.signal == "pred.change" for item in web.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "i've been staring at this bug for two hours",
        "the build took 3 hours",
        "we have been debugging for twenty hours",
    ],
)
def test_number_and_unit_turns_hours_into_a_duration(text: str) -> None:
    """A counted duration is not an opening-hours lookup."""
    cues = extract_cues(views(text), LEXICON, clock=FIXED_NOW.date)

    assert not any(cue.signal == "topic.volatile" and cue.detail == "hours" for cue in cues)
    assert _decide(text).route == "local"


def test_hours_without_a_duration_still_means_opening_hours() -> None:
    """The suppression is specific to a counted duration."""
    cues = extract_cues(views("what are the opening hours?"), LEXICON, clock=FIXED_NOW.date)

    assert any(cue.signal == "topic.volatile" and cue.detail == "hours" for cue in cues)
    assert _decide("what are the opening hours?").route == "web"


@pytest.mark.parametrize("text", SUPPLIED_ARTEFACT_CASES)
def test_supplied_artefact_negation_cancels_volatile_and_change(text: str) -> None:
    """Pasted material is answered locally, without volatile or change bearing."""
    cues = extract_cues(views(text), LEXICON, clock=FIXED_NOW.date)
    decision = _decide(text)

    assert any(cue.signal == "neg.supplied_artifact" for cue in cues)
    assert not any(cue.signal == "topic.volatile" for cue in cues)
    assert not any(cue.signal == "pred.change" for cue in cues)
    assert decision.route == "local"
    assert decision.band == "confident"


@pytest.mark.parametrize(("text", "expected_route", "signal"), NATURAL_LANGUAGE_INSTRUCTION_CASES)
def test_natural_language_instructions_still_set_the_route(
    text: str, expected_route: str, signal: str
) -> None:
    """Instruction phrases remain ordinary lexicon overrides."""
    cues = extract_overrides(views(text), LEXICON)
    decision = _decide(text)

    assert any(cue.signal == signal and cue.source == "override" for cue in cues)
    assert decision.route == expected_route


def test_bang_token_is_ordinary_text_without_a_command_grammar() -> None:
    """A leading ``!web`` is inert; the message is scored exactly as written."""
    decision = _decide("!web what is 2 + 2")

    assert decision.route == "local"
    assert decision.source == "structural"
    assert decision.text == "!web what is 2 + 2"
    assert not any(item.signal.startswith("override.route") for item in decision.evidence)


def test_question_prefix_routes_by_its_content() -> None:
    """A leading ``?status`` contributes no override; the content still routes web."""
    decision = _decide("?status is github down")

    assert decision.route == "web"
    assert decision.source == "structural"
    assert decision.text == "?status is github down"
    assert any(item.signal == "pred.status" for item in decision.evidence)
