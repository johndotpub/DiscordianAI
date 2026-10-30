"""Tests for text views, URL detection, masking, and cue extraction."""

from datetime import date

import pytest

from src.routing.features import (
    Cue,
    extract_cues,
    extract_overrides,
    is_url,
    mask_code,
    views,
)
from src.routing.lexicon import Lexicon

CURRENT_YEAR = 2030
STALE_CLOCK_YEAR = 2032
REPORT_YEAR = 2029


@pytest.fixture
def lexicon() -> Lexicon:
    """Return a freshly loaded bundled lexicon."""
    return Lexicon.load()


def _signature(cues: tuple[Cue, ...]) -> list[tuple[str, str, str, str]]:
    """Drop spans so two surface forms can be compared by signal alone."""
    return [(cue.signal, cue.klass, cue.detail, cue.source) for cue in cues]


def test_contractions_produce_identical_cues(lexicon: Lexicon) -> None:
    """What is X and what's X differ only in spans, never in signals."""
    plain = extract_cues(views("what is the capital of France"), lexicon)
    contracted = extract_cues(views("what's the capital of France"), lexicon)

    assert _signature(plain) == _signature(contracted)
    assert any(cue.signal == "ref.entity" and cue.detail == "France" for cue in contracted)


def test_views_fold_contractions_and_keep_a_span_map() -> None:
    """The folded view expands contractions while mapping every character back."""
    text = "What\u2019s new?"
    text_views = views(text)

    assert text_views.surface == text
    assert "what is new?" in text_views.folded
    assert len(text_views.origin) == len(text_views.folded)
    assert all(0 <= start <= end <= len(text) for start, end in text_views.origin)

    composed = views("Cafe\u0301")
    assert composed.folded == "caf\u00e9"
    assert len(composed.origin) == len(composed.folded)


def test_code_shapes_and_module_attributes_are_not_urls() -> None:
    """Filenames and dotted Python names fail URL detection."""
    assert not is_url("main.py")
    assert not is_url("package.json")
    assert not is_url("asyncio.gather")
    assert not is_url("https://main.py")
    assert is_url("example.com")
    assert is_url("https://x.dev")
    assert is_url("https://example.com/path?q=1")


def test_mask_code_preserves_length_and_line_breaks() -> None:
    """Masking blanks filenames and fences without moving any offset."""
    text = "run main.py\n```sh\nrm -rf /\n```"
    masked = mask_code(text)

    assert len(masked) == len(text)
    assert "main.py" not in masked
    assert [index for index, char in enumerate(masked) if char == "\n"] == [
        index for index, char in enumerate(text) if char == "\n"
    ]


def test_fenced_file_and_masked_filename_emit_code_shape(lexicon: Lexicon) -> None:
    """A fenced block and a bare filename both look like code."""
    fenced = extract_cues(views("```python\nmain.py\n```"), lexicon)
    filename = extract_cues(views("open main.py"), lexicon)

    assert any(cue.signal == "code.shape" for cue in fenced)
    assert any(cue.signal == "code.shape" and cue.detail == "filename" for cue in filename)


def test_delete_one_typo_emits_the_term_class_cue(lexicon: Lexicon) -> None:
    """A misspelt volatile topic still produces its bearing cue."""
    cues = extract_cues(views("wether report"), lexicon)

    assert any(cue.signal == "topic.volatile" and cue.detail == "weather" for cue in cues)


def test_deixis_is_framing_alone_and_bearing_with_a_topic(lexicon: Lexicon) -> None:
    """Time deixis cannot carry a bearing decision by itself."""
    alone = extract_cues(views("yesterday"), lexicon)
    together = extract_cues(views("weather yesterday"), lexicon)

    assert all(cue.klass == "framing" for cue in alone if cue.signal == "time.deixis")
    assert any(cue.klass == "bearing" for cue in together if cue.signal == "time.deixis")


def test_time_year_uses_the_injected_clock(lexicon: Lexicon) -> None:
    """A year only counts when it is the current year or the one before it."""
    fresh = extract_cues(
        views(f"the {REPORT_YEAR} report"),
        lexicon,
        clock=lambda: date(CURRENT_YEAR, 1, 1),
    )
    stale = extract_cues(
        views(f"the {REPORT_YEAR} report"),
        lexicon,
        clock=lambda: date(STALE_CLOCK_YEAR, 1, 1),
    )

    assert any(cue.signal == "time.year" and cue.detail == str(REPORT_YEAR) for cue in fresh)
    assert not any(cue.signal == "time.year" for cue in stale)


def test_override_patterns_are_exposed_as_override_cues(lexicon: Lexicon) -> None:
    """Explicit search and local-only instructions remain separate cues."""
    web = extract_overrides(views("please search the web"), lexicon)
    local = extract_overrides(views("answer from memory"), lexicon)

    assert any(cue.signal == "override.web_instruction" for cue in web)
    assert any(cue.signal == "override.local_instruction" for cue in local)
