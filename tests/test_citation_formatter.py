"""Focused tests for citation styling and bare-URL cleanup."""

import asyncio
import re

import pytest

from src import perplexity_processing
from tests.golden_cases import (
    CASES_BY_SURFACE,
    SURFACE_CITATION_EMBED,
    SURFACE_FORMAT_CITATIONS,
)
from tests.golden_runner import load_fixture, replay_case

_MESSAGE_LINK = re.compile(r"\[(\d+)\]\(([^)]+)\)")


def _message_style_to_embed(text: str) -> str:
    """Turn every message-style citation link into its embed-style form."""
    return _MESSAGE_LINK.sub(r"[[\1]](\2)", text)


def _strip_case(count: int) -> tuple[str, list[str], str]:
    """Build text with bare and markdown-wrapped URLs plus the expected output."""
    urls = [f"https://example.com/source/{index:02d}" for index in range(1, count + 1)]
    text_lines = []
    expected_lines = []
    for index, url in enumerate(urls, start=1):
        text_lines.append(f"Source {index:02d}: {url} | [doc]({url}) | trailing {url} )")
        expected_lines.append(f"Source {index:02d}:  | [doc]({url}) | trailing {url} )")
    return "\n".join(text_lines), urls, "\n".join(expected_lines)


class _CountingPattern:
    """Proxy that records each compiled-pattern substitution."""

    def __init__(self, pattern: re.Pattern[str], calls: dict[str, int]) -> None:
        self._pattern = pattern
        self._calls = calls

    def sub(self, replacement, string: str, count: int = 0) -> str:
        self._calls["sub"] += 1
        return self._pattern.sub(replacement, string, count)


class _CountingRegex:
    """Minimal ``re`` stand-in that counts compiles and substitutions."""

    def __init__(self) -> None:
        self.calls = {"compile": 0, "sub": 0}

    def escape(self, value: str) -> str:
        return re.escape(value)

    def compile(self, pattern: str, flags: int = 0) -> _CountingPattern:
        self.calls["compile"] += 1
        return _CountingPattern(re.compile(pattern, flags), self.calls)

    def sub(self, pattern, replacement, string: str, count: int = 0, flags: int = 0) -> str:
        self.calls["sub"] += 1
        return re.sub(pattern, replacement, string, count=count, flags=flags)


def test_message_and_embed_styles_differ_only_in_brackets():
    from src.perplexity_processing import format_citations

    text = "Known [1], missing [3], markdown [guide](https://example.com/guide), and second [2]."
    citations = {
        "1": "https://example.com/source/one",
        "2": "https://example.com/source/two",
    }

    message = format_citations(text, citations, style="message")
    embed = format_citations(text, citations, style="embed")

    assert message == (
        "Known [1](https://example.com/source/one), missing [3], "
        "markdown [guide](https://example.com/guide), and second "
        "[2](https://example.com/source/two)."
    )
    assert _message_style_to_embed(message) == embed


@pytest.mark.parametrize("count", [1, 5, 20])
def test_bare_url_strip_output_is_identical_for_each_url_count(count):
    text, urls, expected = _strip_case(count)

    assert perplexity_processing._clean_bare_urls_safely(text, urls) == expected


@pytest.mark.parametrize("count", [1, 5, 20])
def test_bare_url_strip_uses_one_regex_pass(monkeypatch, count):
    text, urls, _ = _strip_case(count)
    counting_regex = _CountingRegex()
    monkeypatch.setattr(perplexity_processing, "re", counting_regex)

    perplexity_processing._clean_bare_urls_safely(text, urls)

    assert counting_regex.calls == {"compile": 1, "sub": 1}


_CITATION_GOLDEN_CASES = [
    case
    for surface in (SURFACE_FORMAT_CITATIONS, SURFACE_CITATION_EMBED)
    for case in CASES_BY_SURFACE[surface]
]


@pytest.mark.parametrize(
    "case", _CITATION_GOLDEN_CASES, ids=[case["id"] for case in _CITATION_GOLDEN_CASES]
)
def test_golden_citation_fixtures_pass_without_regeneration(case):
    expected = load_fixture(case["surface"])["cases"][case["id"]]

    assert asyncio.run(replay_case(case)).result == expected
