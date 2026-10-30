"""Data-only definitions of the golden behaviour corpus.

Each case is a plain dictionary with an ``id``, the ``surface`` under test and
the ``inputs`` required to replay it.  There are deliberately no assertions in
this module: it is imported by both the pytest suite and the regeneration
script so the two always exercise exactly the same inputs.
"""

from typing import Any

SURFACE_SEND_SPLIT = "send_split_message"
SURFACE_SEND_SPLIT_EMBED = "send_split_message_with_embed"
SURFACE_FORMAT_CITATIONS = "format_citations_for_discord"
SURFACE_CITATION_EMBED = "citation_embed_formatter"
SURFACE_API_PARAMS = "build_api_params"

SURFACES = (
    SURFACE_SEND_SPLIT,
    SURFACE_SEND_SPLIT_EMBED,
    SURFACE_FORMAT_CITATIONS,
    SURFACE_CITATION_EMBED,
    SURFACE_API_PARAMS,
)

MENTION_PREFIX = "<@987654321> "
PREFIX_LENGTH = len(MENTION_PREFIX)
PREFIX_FIT_LENGTH = 2000 - PREFIX_LENGTH
PREFIX_OVERFLOW_LENGTH = PREFIX_FIT_LENGTH + 1

_PROSE_UNIT = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "

CITATION_URLS = {str(index): f"https://example.com/source/{index}" for index in range(1, 21)}


def _prose(length: int) -> str:
    """Return deterministic prose truncated to exactly ``length`` characters."""
    if length <= 0:
        return ""
    repeats = (length // len(_PROSE_UNIT)) + 1
    return (_PROSE_UNIT * repeats)[:length]


def _alpha(length: int, char: str = "A") -> str:
    """Return a run of ``char`` with exactly ``length`` characters."""
    return char * max(0, length)


def _citation_only_content(length: int, marker: str = "[1]", char: str = "A") -> str:
    """Return content of exactly ``length`` chars, starting with ``marker``."""
    return marker + _alpha(length - len(marker), char)


def _send_case(  # noqa: PLR0913
    case_id: str,
    message: str,
    *,
    suppress_embeds: bool = False,
    original_message: bool = False,
    mention_prefix: str | None = None,
    recursion_depth: int = 0,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "surface": SURFACE_SEND_SPLIT,
        "inputs": {
            "message": message,
            "suppress_embeds": suppress_embeds,
            "original_message": original_message,
            "mention_prefix": mention_prefix,
            "recursion_depth": recursion_depth,
        },
    }


def _embed_send_case(  # noqa: PLR0913
    case_id: str,
    message: str,
    citations: dict[str, str] | None,
    *,
    title: str | None = None,
    footer: str | None = None,
    original_message: bool = False,
    mention_prefix: str | None = None,
    recursion_depth: int = 0,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "surface": SURFACE_SEND_SPLIT_EMBED,
        "inputs": {
            "message": message,
            "citations": citations,
            "embed": {
                "title": title,
                "description": "placeholder description",
                "footer": footer,
                "color": 0x5865F2,
            },
            "original_message": original_message,
            "mention_prefix": mention_prefix,
            "recursion_depth": recursion_depth,
        },
    }


def _format_case(
    case_id: str,
    function_name: str,
    text: str,
    citations: dict[str, str] | None,
    *,
    linkify: bool = True,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {"text": text, "citations": citations}
    if function_name == "format_citations_for_discord":
        inputs["linkify"] = linkify
    return {
        "id": case_id,
        "surface": SURFACE_FORMAT_CITATIONS,
        "inputs": {"function": function_name, **inputs},
    }


def _citation_embed_case(
    case_id: str,
    content: str,
    citations: dict[str, str],
    *,
    title: str | None = None,
    footer_text: str | None = None,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "surface": SURFACE_CITATION_EMBED,
        "inputs": {
            "content": content,
            "citations": citations,
            "title": title,
            "footer_text": footer_text,
        },
    }


def _api_params_case(  # noqa: PLR0913
    case_id: str,
    model: str,
    system: str,
    user_msg: str,
    tokens: int,
    *,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "model": model,
        "system": system,
        "user_msg": user_msg,
        "tokens": tokens,
    }
    if history is not None:
        inputs["history"] = history
    return {
        "id": case_id,
        "surface": SURFACE_API_PARAMS,
        "inputs": inputs,
    }


SEND_SPLIT_CASES = [
    # Body sizes, no prefix, channel.send.
    _send_case("a-body-0000-send", _prose(0)),
    _send_case("a-body-0001-send", _prose(1)),
    _send_case("a-body-0100-send", _prose(100)),
    _send_case("a-body-1990-send", _prose(1990)),
    _send_case("a-body-1999-send", _prose(1999)),
    _send_case("a-body-2000-send", _prose(2000)),
    _send_case("a-body-2001-send", _prose(2001)),
    _send_case("a-body-2500-send", _prose(2500)),
    _send_case("a-body-4000-send", _prose(4000)),
    _send_case("a-body-9000-send", _prose(9000)),
    # original_message present: reply() instead of send().
    _send_case("a-body-0001-reply", _prose(1), original_message=True),
    _send_case("a-body-2000-reply", _prose(2000), original_message=True),
    _send_case(
        "a-body-2001-reply-suppress",
        _prose(2001),
        original_message=True,
        suppress_embeds=True,
    ),
    _send_case("a-body-2500-reply", _prose(2500), original_message=True),
    _send_case(
        "a-body-2500-reply-suppress",
        _prose(2500),
        original_message=True,
        suppress_embeds=True,
    ),
    _send_case(
        "a-body-4000-reply-suppress",
        _prose(4000),
        original_message=True,
        suppress_embeds=True,
    ),
    _send_case("a-body-9000-reply", _prose(9000), original_message=True),
    # suppress_embeds=True without an original message.
    _send_case("a-body-0100-send-suppress", _prose(100), suppress_embeds=True),
    _send_case("a-body-1999-send-suppress", _prose(1999), suppress_embeds=True),
    _send_case("a-body-2000-send-suppress", _prose(2000), suppress_embeds=True),
    _send_case("a-body-2001-send-suppress", _prose(2001), suppress_embeds=True),
    _send_case("a-body-2500-send-suppress", _prose(2500), suppress_embeds=True),
    _send_case("a-body-4000-send-suppress", _prose(4000), suppress_embeds=True),
    # Mention prefix consumes part of the first chunk.
    _send_case(
        "a-prefix-fit-1987-send",
        _alpha(PREFIX_FIT_LENGTH),
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-overflow-1988-send",
        _alpha(PREFIX_OVERFLOW_LENGTH),
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-fit-1987-reply",
        _alpha(PREFIX_FIT_LENGTH),
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-overflow-1988-reply",
        _alpha(PREFIX_OVERFLOW_LENGTH),
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-2000-body-send",
        _alpha(2000),
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-2000-body-reply-suppress",
        _alpha(2000),
        original_message=True,
        suppress_embeds=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-2500-body-send",
        _alpha(2500),
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-2500-body-reply",
        _alpha(2500),
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-4000-body-send-suppress",
        _alpha(4000),
        suppress_embeds=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-9000-body-reply-suppress",
        _alpha(9000),
        original_message=True,
        suppress_embeds=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-0100-body-send",
        _prose(100),
        mention_prefix=MENTION_PREFIX,
    ),
    _send_case(
        "a-prefix-empty-body-reply",
        "",
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    # Prefixes at and over the message limit are dropped.
    _send_case(
        "a-prefix-exactly-2000-send",
        _prose(100),
        mention_prefix=MENTION_PREFIX + "x" * (2000 - PREFIX_LENGTH),
    ),
    _send_case(
        "a-prefix-over-2000-reply",
        _prose(100),
        original_message=True,
        mention_prefix=MENTION_PREFIX + "x" * (2001 - PREFIX_LENGTH),
    ),
    # Code fences around the split point.
    _send_case(
        "a-fence-straddle-split-before",
        _alpha(1850) + "```\n" + _alpha(300, "B") + "\n```" + _alpha(100, "C"),
    ),
    _send_case(
        "a-fence-straddle-split-after",
        _alpha(1750) + "```\n" + _alpha(190, "B") + "\n```" + _alpha(200, "D"),
    ),
    _send_case(
        "a-fence-adjacent",
        _alpha(1850) + "```\nfirst\n```\n```\nsecond\n```\n" + _alpha(200, "Y"),
    ),
    _send_case(
        "a-fence-nested-looking",
        _alpha(1850) + "````\n```python\nprint('x')\n```\n````\n" + _alpha(200, "S"),
    ),
    _send_case(
        "a-fence-unclosed",
        _alpha(1850) + "```python\n" + _alpha(500, "V"),
    ),
    # Unicode and URL content.
    _send_case("a-unicode-emoji", "\U0001f642" * 2100),
    _send_case(
        "a-unicode-emoji-zwj", "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466" * 400
    ),
    _send_case("a-unicode-combining", "x" + ("e\u0301" * 1100)),
    _send_case("a-unicode-cjk", "\u6f22\u5b57\u4eee\u540d\u4ea4\u3058\u308a\u6587" * 300),
    _send_case(
        "a-unicode-mixed",
        ("\u00e9moji \U0001f642 \u6f22\u5b57 " * 250),
    ),
    _send_case(
        "a-url-intact-space-boundary",
        ("word " * 300) + "https://example.com/path?q=golden&x=1" + " " + ("tail " * 400),
    ),
    _send_case(
        "a-url-intact-newline-boundary",
        _alpha(1000) + "\nhttps://example.com/a/very/long/path?with=query\n" + _alpha(1000, "B"),
    ),
    # Sanitisation and boundary styles.
    _send_case("a-sanitize-everyone", "hello @everyone and @here"),
    _send_case("a-sanitize-here-split", "@here " * 400),
    _send_case(
        "a-newline-rich-split",
        "".join(f"line {index:03d}\n" for index in range(300)),
    ),
    _send_case(
        "a-sentence-boundary-split",
        "".join(f"This is sentence number {index}. " for index in range(100)),
    ),
    _send_case("a-single-long-word-2500", _alpha(2500)),
    _send_case(
        "a-prefix-near-limit-1999-send",
        _alpha(100),
        mention_prefix=MENTION_PREFIX + "x" * (1999 - PREFIX_LENGTH),
    ),
    _send_case(
        "a-prefix-near-limit-2000-reply",
        _alpha(100),
        original_message=True,
        mention_prefix=MENTION_PREFIX + "x" * (2000 - PREFIX_LENGTH),
    ),
]


SEND_SPLIT_EMBED_CASES = [
    _embed_send_case("b-short-0-citations", _prose(100), {}),
    _embed_send_case(
        "b-short-1-citation",
        "Short answer with citation [1].",
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-short-5-citations",
        "Answer [1] and [2] and [3] and [4] and [5].",
        {str(index): CITATION_URLS[str(index)] for index in range(1, 6)},
    ),
    _embed_send_case(
        "b-short-20-citations",
        "Sources: " + " ".join(f"[{index}]" for index in range(1, 21)),
        {str(index): CITATION_URLS[str(index)] for index in range(1, 21)},
    ),
    _embed_send_case(
        "b-length-3838-one-citation",
        _citation_only_content(3838),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-length-3839-one-citation",
        _citation_only_content(3839),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-length-3840-one-citation",
        _citation_only_content(3840),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-length-3841-one-citation",
        _citation_only_content(3841),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-length-3844-tail-citation",
        _alpha(3840) + " [5]",
        {"5": CITATION_URLS["5"]},
    ),
    _embed_send_case(
        "b-long-5000-tail-citation",
        _alpha(3900) + " [1] " + _alpha(1000, "B"),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-long-5000-head-citation-only",
        "[1] " + _alpha(4900),
        {"1": CITATION_URLS["1"]},
    ),
    _embed_send_case(
        "b-long-5000-no-citations",
        _alpha(5000, "C"),
        {},
    ),
    _embed_send_case(
        "b-long-5000-20-tail-citations",
        _alpha(3900)
        + " "
        + " ".join(f"[{index}]" for index in range(1, 21))
        + " "
        + _alpha(900, "B"),
        {str(index): CITATION_URLS[str(index)] for index in range(1, 21)},
    ),
    _embed_send_case(
        "b-long-9000-five-spread-citations",
        _alpha(1000)
        + "[1]"
        + _alpha(1000, "B")
        + "[2]"
        + _alpha(1000, "C")
        + "[3]"
        + _alpha(1000, "D")
        + "[4]"
        + _alpha(1000, "E")
        + "[5]"
        + _alpha(3000, "F"),
        {str(index): CITATION_URLS[str(index)] for index in range(1, 6)},
    ),
    _embed_send_case(
        "b-long-9000-reply-prefix-no-citations",
        _alpha(9000, "G"),
        {},
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _embed_send_case(
        "b-long-5000-reply-tail-citation",
        _alpha(3900) + " [1] " + _alpha(1000, "B"),
        {"1": CITATION_URLS["1"]},
        original_message=True,
        mention_prefix=MENTION_PREFIX,
    ),
    _embed_send_case(
        "b-short-citation-reply-duplicate-tail",
        "Short content [1]",
        {"1": CITATION_URLS["1"]},
        original_message=True,
    ),
    _embed_send_case(
        "b-depth-10-guard-send",
        _alpha(5000, "G"),
        {"1": CITATION_URLS["1"]},
        recursion_depth=10,
    ),
    _embed_send_case(
        "b-depth-10-guard-reply",
        _alpha(5000, "G"),
        {"1": CITATION_URLS["1"]},
        original_message=True,
        mention_prefix=MENTION_PREFIX,
        recursion_depth=10,
    ),
    _embed_send_case(
        "b-depth-9-long-recurses-to-guard",
        _alpha(3900) + " [1] " + _alpha(5000, "H"),
        {"1": CITATION_URLS["1"]},
        recursion_depth=9,
    ),
    _embed_send_case(
        "b-custom-footer-preserved",
        "Short answer [1].",
        {"1": CITATION_URLS["1"]},
        footer="Custom footer",
    ),
    _embed_send_case(
        "b-custom-title-preserved",
        "Short answer [1].",
        {"1": CITATION_URLS["1"]},
        title="Answer title",
    ),
]


FORMAT_CITATION_CASES = [
    _format_case(
        "c-format-linkify-basic",
        "format_citations_for_discord",
        "Answer with a source [1].",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-format-plain-basic",
        "format_citations_for_discord",
        "Answer with a source [1].",
        {"1": CITATION_URLS["1"]},
        linkify=False,
    ),
    _format_case(
        "c-format-bare-url",
        "format_citations_for_discord",
        "See https://example.com/raw and source [1].",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-format-duplicate-markers",
        "format_citations_for_discord",
        "First [1], second [1], third [1].",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-format-out-of-range",
        "format_citations_for_discord",
        "Known [1], unknown [3].",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-format-none-citations",
        "format_citations_for_discord",
        "No mapping [1].",
        None,
    ),
    _format_case(
        "c-format-empty-citations",
        "format_citations_for_discord",
        "No mapping [1].",
        {},
    ),
    _format_case(
        "c-format-mixed-markdown",
        "format_citations_for_discord",
        "**Bold** [link](https://example.com/doc) and [1] and `[2]`.",
        {"1": CITATION_URLS["1"], "2": CITATION_URLS["2"]},
    ),
    _format_case(
        "c-format-multiple-markers",
        "format_citations_for_discord",
        "Sources [1], [2], [3].",
        {str(index): CITATION_URLS[str(index)] for index in range(1, 4)},
    ),
    _format_case(
        "c-format-no-markers",
        "format_citations_for_discord",
        "There are no citation markers here.",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-format-adjacent-markers",
        "format_citations_for_discord",
        "Adjacent [1][2] markers.",
        {"1": CITATION_URLS["1"], "2": CITATION_URLS["2"]},
    ),
    _format_case(
        "c-format-numbered-list",
        "format_citations_for_discord",
        "1. [1]\n2. [2]\n3. [3]",
        {str(index): CITATION_URLS[str(index)] for index in range(1, 4)},
    ),
    _format_case(
        "c-normalize-empty-citations",
        "_normalize_citation_text",
        "  Keep [1] and trim.  ",
        {},
    ),
    _format_case(
        "c-normalize-markdown-matching",
        "_normalize_citation_text",
        "Source [1](https://example.com/source/1) here.",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-markdown-nonmatching",
        "_normalize_citation_text",
        "Source [1](https://different.example/doc) here.",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-bare-url",
        "_normalize_citation_text",
        "See https://example.com/source/1 for details.",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-url-only-line",
        "_normalize_citation_text",
        "First line\nhttps://example.com/source/1\nLast line",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-inline-marker-url",
        "_normalize_citation_text",
        "Result [1]: https://example.com/source/1",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-multiple-lines",
        "_normalize_citation_text",
        "[1] One\n[2] Two\n\n https://example.com/source/2",
        {"1": CITATION_URLS["1"], "2": CITATION_URLS["2"]},
    ),
    _format_case(
        "c-normalize-preserve-spacing",
        "_normalize_citation_text",
        "  indented text [1]  \n\n  next line  ",
        {"1": CITATION_URLS["1"]},
    ),
    _format_case(
        "c-normalize-no-citations-mapping",
        "_normalize_citation_text",
        "  Nothing to clean [4].  ",
        None,
    ),
]


CITATION_EMBED_CASES = [
    _citation_embed_case("d-basic-no-citations", "Hello world.", {}),
    _citation_embed_case(
        "d-basic-one-citation",
        "Hello [1].",
        {"1": CITATION_URLS["1"]},
    ),
    _citation_embed_case(
        "d-five-citations",
        "Sources [1] [2] [3] [4] [5].",
        {str(index): CITATION_URLS[str(index)] for index in range(1, 6)},
    ),
    _citation_embed_case(
        "d-twenty-citations",
        "Sources " + " ".join(f"[{index}]" for index in range(1, 21)) + ".",
        {str(index): CITATION_URLS[str(index)] for index in range(1, 21)},
    ),
    _citation_embed_case(
        "d-custom-title",
        "Title test [1].",
        {"1": CITATION_URLS["1"]},
        title="Golden title",
    ),
    _citation_embed_case(
        "d-custom-footer",
        "Footer test [1].",
        {"1": CITATION_URLS["1"]},
        footer_text="Custom footer text",
    ),
    _citation_embed_case(
        "d-empty-content",
        "",
        {},
    ),
    _citation_embed_case(
        "d-out-of-range-citation",
        "Known [1], unknown [9].",
        {"1": CITATION_URLS["1"]},
    ),
    _citation_embed_case(
        "d-description-3840",
        _alpha(3840),
        {},
    ),
    _citation_embed_case(
        "d-description-3841",
        _alpha(3841),
        {},
    ),
    _citation_embed_case(
        "d-description-4096",
        _alpha(4096),
        {},
    ),
    _citation_embed_case(
        "d-description-4097",
        _alpha(4097),
        {},
    ),
    _citation_embed_case(
        "d-mixed-markdown-citation",
        "**Bold** [link](https://example.com/doc) with [1].",
        {"1": CITATION_URLS["1"]},
    ),
]


API_PARAMS_CASES = [
    _api_params_case("e-empty-values", "", "", "", 0),
    _api_params_case(
        "e-standard-values",
        "sonar-pro",
        "You are a helpful assistant.",
        "What is today's news?",
        8000,
    ),
    _api_params_case(
        "e-unicode-values",
        "sonar",
        "You are helpful. \U0001f642",
        "\u4eca\u5929\u306e\u5929\u6c17\u306f\uff1f",
        1234,
    ),
    _api_params_case(
        "e-multiline-system",
        "sonar-pro",
        "Line one.\nLine two.\nLine three.",
        "Summarise the above.",
        512,
    ),
    _api_params_case(
        "e-multiline-user",
        "sonar-pro",
        "System prompt",
        "First line\nSecond line\n\nFourth line",
        2048,
    ),
    _api_params_case(
        "e-json-ish-content",
        "sonar",
        'Return JSON with keys "answer" and "sources".',
        '{"question": "golden behaviour?"}',
        777,
    ),
    _api_params_case(
        "e-long-system",
        "sonar-pro",
        _prose(5000),
        "Short question",
        4096,
    ),
    _api_params_case(
        "e-large-token-budget",
        "sonar-pro",
        "System",
        "User",
        120000,
    ),
    _api_params_case(
        "e-history-one-turn",
        "sonar-pro",
        "You are a helpful assistant with access to current web information.",
        "And what about the second one?",
        8000,
        history=[
            {"role": "user", "content": "Name two novels by Frank Herbert."},
        ],
    ),
    _api_params_case(
        "e-history-three-turns",
        "sonar",
        "You are a helpful assistant.",
        "Who wrote it?",
        2048,
        history=[
            {"role": "user", "content": "Name two novels by Frank Herbert."},
            {"role": "assistant", "content": "Dune and Dune Messiah."},
            {"role": "user", "content": "When was the first one published?"},
        ],
    ),
]


CASES_BY_SURFACE: dict[str, list[dict[str, Any]]] = {
    SURFACE_SEND_SPLIT: SEND_SPLIT_CASES,
    SURFACE_SEND_SPLIT_EMBED: SEND_SPLIT_EMBED_CASES,
    SURFACE_FORMAT_CITATIONS: FORMAT_CITATION_CASES,
    SURFACE_CITATION_EMBED: CITATION_EMBED_CASES,
    SURFACE_API_PARAMS: API_PARAMS_CASES,
}

ALL_CASES = [case for surface in SURFACES for case in CASES_BY_SURFACE[surface]]
