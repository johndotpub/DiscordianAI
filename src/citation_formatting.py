"""Shared rendering for numbered Perplexity citations."""

import re

from .config import CITATION_PATTERN

_CITATION_TEMPLATES = {
    "message": "[{number}]({url})",
    "embed": "[[{number}]]({url})",
}
_PLAIN_CITATION_TEMPLATE = "[{number}]"
_SAFE_CITATION_URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]\\]+", re.IGNORECASE)


def is_renderable_citation_url(url: str) -> bool:
    """Return True when a citation URL can safely sit inside a markdown link.

    Parentheses, brackets, angle brackets, backslashes, and whitespace are
    rejected because they can terminate the link early and leave the remainder
    as attacker controlled markdown.

    Args:
        url: Citation URL to check.

    Returns:
        True when the URL is a bounded ``http(s)`` URL without link-breaking
        characters.
    """
    return bool(_SAFE_CITATION_URL_PATTERN.fullmatch(str(url).strip()))


def renderable_citations(citations: dict[str, str] | None) -> dict[str, str]:
    """Return the citation entries that may be rendered as links.

    A citation parsed from the model's own text carries a ``untrusted_urls``
    attribute on the mapping. Those entries remain labelled in the text but
    are excluded here so they can never become a clickable link.

    Args:
        citations: Mapping of citation numbers to URLs, optionally carrying an
            ``untrusted_urls`` set.

    Returns:
        A plain dictionary containing only trusted, safely renderable entries.
    """
    if not citations:
        return {}
    untrusted = {str(url).strip() for url in getattr(citations, "untrusted_urls", ())}
    return {
        number: url
        for number, url in citations.items()
        if str(url).strip() not in untrusted and is_renderable_citation_url(url)
    }


def _render_citations(text: str, citations: dict[str, str], template: str) -> str:
    if not citations:
        return text

    def replace_citation(match: re.Match[str]) -> str:
        citation_num = match.group(1)
        if citation_num not in citations:
            return match.group(0)
        return template.format(number=citation_num, url=citations[citation_num])

    return CITATION_PATTERN.sub(replace_citation, text)


def format_citations(text: str, citations: dict[str, str], *, style: str = "message") -> str:
    """Render known citation markers as Discord links in the requested style.

    Args:
        text: Text potentially containing numbered markers such as ``[1]``.
        citations: Mapping from citation number strings to source URLs.
        style: ``"message"`` renders ``[n](url)`` and ``"embed"`` renders
            ``[[n]](url)`` for Discord embed descriptions.

    Returns:
        The text with known citation markers rendered as links. Unknown
        markers and text without a citation mapping are returned unchanged.

    Raises:
        ValueError: If ``style`` is not a supported citation style.
    """
    try:
        template = _CITATION_TEMPLATES[style]
    except KeyError:
        msg = f"Unsupported citation style: {style!r}"
        raise ValueError(msg) from None
    return _render_citations(text, citations, template)


def _format_unlinked_citations(text: str, citations: dict[str, str]) -> str:
    """Render known citation markers as plain ``[n]`` markers."""
    return _render_citations(text, citations, _PLAIN_CITATION_TEMPLATE)
