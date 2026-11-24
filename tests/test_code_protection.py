"""Differential and named-case tests for the shared code-region sanitiser.

The sanitiser and the splitter now use one parser-backed region function.
These tests check the delivered text, not the helper: the content path, the
embed description path, and every delivered chunk are examined with two
independent Markdown parsers whenever those parsers can handle the input.
"""

import random
import time
from unittest.mock import MagicMock

import discord
from discord_markdown_ast_parser import parse as parse_discord_markdown
from discord_markdown_ast_parser.parser import NodeType
from markdown_it import MarkdownIt
import pytest

from src import message_splitter
from src.message_splitter import (
    protected_code_regions,
    sanitize_for_discord,
    send_formatted_message,
    send_split_message,
)

MARKDOWN = MarkdownIt("commonmark")
ZERO_WIDTH_SPACE = "\u200b"
MENTIONS = ("@everyone", "@here", "<@1>", "<@&1>", "<#1>")

NAMED_CASES = [
    (
        "f1-mid-line-fence",
        "intro ```\n```\n" + ("line\n" * 80) + "https://evil.example/gift\n```\n",
    ),
    (
        "f1-python-variant",
        "```\n```python\n" + ("line\n" * 80) + "https://evil.example/gift\n```\n",
    ),
    ("f2-warning-line", "[Warning]: do not run it as root."),
    ("f2-source-list", "Sources:\n[1]: https://en.wikipedia.org/wiki/Paris"),
    ("f5-two-urls", "https://a.example/x)https://evil.example/gift"),
    ("f5-query", "?next=https://evil.example/x"),
    ("f5-comma", "one,https://evil.example/x"),
    ("inline-code-then-link", "`x` [Claim your Nitro](https://evil.example/gift) `"),
    ("link-label-is-code", "[`a](https://evil.example/b)`"),
    ("unclosed-fence", "```\n[x](https://evil.example/d)"),
    ("escaped-backticks", "\\`[x](https://evil.example/e)\\`"),
    ("autolink", "<https://evil.example/f>"),
    ("reference-link", "[a][1]\n\n[1]: https://evil.example/g"),
    ("escaped-bracket", "[a\\]b](https://e)"),
    ("definition-in-quote", "> [a][1]\n>\n> [1]: https://evil.example/g"),
    ("destination-next-line", "[a]\n(https://evil.example/g)"),
    ("multi-line-label", "[a\nb](https://evil.example/g)"),
    ("nul-character", "a\x00b [x](https://evil.example/g)"),
    ("tilde-fence", "x\n~~~\n[a](https://evil.example/g)\n~~~\ny"),
    ("indented-code", "text\n\n    [x](https://evil.example/e)\n"),
]

NESTED_DEPTHS = (2, 10, 12, 100)

FENCE_INNER_RUN_CASES = [
    (
        "closer-followed-by-text",
        "```\nfoo\n```bar [x](https://evil.example/c)\n```\n",
    ),
    (
        "mid-line-inner-run",
        "```\nfoo ``` [x](https://evil.example/d) bar\n```\n",
    ),
    (
        "four-backtick-inner-run",
        "```\nfoo\n````bar [x](https://evil.example/c)\n```\n",
    ),
    (
        "balanced-inner-run",
        "```\nfoo ```x``` [x](https://evil.example/e) bar\n```\n",
    ),
]

INLINE_DIVERGENCE_CASES = [
    ("escaped-opener-shifts-pairing", "\\`x`[x](https://evil.example/e)`"),
    ("blank-line-shifts-pairing", "`\n\nx`[x](https://evil.example/e)`"),
    ("different-run-length", "``a` [x](https://evil.example/e) b``"),
]

FRAGMENTS = [
    "`",
    "``",
    "```",
    "````",
    "`````",
    "\\",
    "\\\\",
    "~~~",
    "\n```\n",
    "\n~~~\n",
    "\n    indented\n",
    "\r\n",
    "<div>",
    "</div>",
    "![alt](https://evil.example/image)",
    "<https://evil.example/auto>",
    "[1]: https://evil.example/ref",
    "[a [b] c]",
    "(https://evil.example/paren)",
    "[x]",
    "[x][1]",
    "\u200b",
    "\x00",
    "\n",
    " ",
    "text",
    "`code`",
    "``code``",
    "[`a`](https://evil.example/b)",
    "@everyone",
    "@here",
    "<@1>",
    "<@&1>",
    "<#1>",
    "```x```",
    "\n```bar\n",
    "\n````bar\n",
    " foo ``` bar\n",
    "`a\n\n`",
]


def _oracle_parses(text: str) -> bool:
    """Return False when the Discord oracle crashes on ``text``."""
    try:
        parse_discord_markdown(text)
    except (TypeError, ValueError):
        return False
    return True


def _generated_cases(count: int = 1_000) -> list[str]:
    """Return a fixed-seed adversarial corpus with at least one thousand cases.

    The Discord oracle cannot parse every adversarial shape, so a bounded share
    of such inputs is kept and the rest are skipped. The corpus stays fixed for
    a given seed and never lets an oracle crash hide a sanitised-output failure.
    """
    generator = random.Random(20261123)  # noqa: S311 - fixed seed, not cryptography
    crash_budget = count // 20
    cases: list[str] = []
    crashes = 0
    while len(cases) < count:
        case = "".join(generator.choice(FRAGMENTS) for _ in range(generator.randint(3, 10)))
        if _oracle_parses(case):
            cases.append(case)
        elif crashes < crash_budget:
            cases.append(case)
            crashes += 1
    return cases


CORPUS = [*[case for _name, case in NAMED_CASES], *_generated_cases()]


def _discord_urls_outside_code(text: str) -> list[str] | None:
    """Return URL node values outside code, or None when the oracle crashes."""
    try:
        nodes = parse_discord_markdown(text)
    except (TypeError, ValueError):
        return None

    urls: list[str] = []

    def walk(items) -> None:
        for node in items:
            if node.node_type in (NodeType.CODE_INLINE, NodeType.CODE_BLOCK):
                continue
            if node.node_type in (NodeType.URL_WITH_PREVIEW, NodeType.URL_WITHOUT_PREVIEW):
                urls.append(node.url or "")
            if node.children:
                walk(node.children)

    walk(nodes)
    return urls


def _assert_no_live_link(sanitized: str, source: str, where: str) -> None:
    """Assert both parsers see no live link and no surviving mention."""
    rendered = MARKDOWN.render(sanitized)
    assert "<a " not in rendered, f"{where} rendered a link from {source!r}: {rendered!r}"
    assert "<img " not in rendered, f"{where} rendered an image from {source!r}: {rendered!r}"

    urls = _discord_urls_outside_code(sanitized)
    if urls is not None:
        for url in urls:
            assert ZERO_WIDTH_SPACE in url, f"{where} kept a live URL from {source!r}: {url!r}"

    regions = protected_code_regions(sanitized)
    masked = list(sanitized)
    for region in regions:
        masked[region.start : region.end] = " " * (region.end - region.start)
    assert "](" not in "".join(masked), f"{where} left ']( ' outside code from {source!r}"

    for mention in MENTIONS:
        assert mention not in sanitized, f"{where} kept {mention!r} from {source!r}"


def _assert_corpus_in_sanitised_output() -> None:
    for case in CORPUS:
        sanitized = sanitize_for_discord(case)
        _assert_no_live_link(sanitized, case, "message")


class _RecordingChannel:
    """Capture Discord send calls without a network connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send(self, content: str, **kwargs) -> None:
        self.calls.append((content, kwargs))


def _deps() -> dict:
    return {"logger": MagicMock()}


def test_generated_corpus_has_at_least_one_thousand_fixed_cases() -> None:
    """The differential corpus is fixed, generated, and large enough."""
    generated = _generated_cases()
    assert len(generated) >= 1_000
    assert generated == _generated_cases()


def test_generated_corpus_oracle_crashes_stay_within_five_percent() -> None:
    """An oracle crash is skipped, not fatal, and must stay a small minority."""
    generated = _generated_cases()
    crashes = sum(not _oracle_parses(case) for case in generated)
    assert (
        crashes <= len(generated) * 0.05
    ), f"{crashes} of {len(generated)} generated cases crashed the Discord oracle"


def test_differential_sanitised_output_has_no_live_link() -> None:
    """A fixed corpus cannot smuggle an anchor, image, URL, or mention."""
    _assert_corpus_in_sanitised_output()


@pytest.mark.asyncio
async def test_differential_content_chunks_have_no_live_link() -> None:
    """Every delivered content chunk is checked after splitting."""
    for case in CORPUS:
        channel = _RecordingChannel()
        await send_formatted_message(channel, case, _deps())
        for content, _kwargs in channel.calls:
            _assert_no_live_link(content, case, "content chunk")


@pytest.mark.asyncio
async def test_differential_embed_descriptions_have_no_live_link() -> None:
    """The embed description path applies the same rule."""
    for case in CORPUS:
        channel = _RecordingChannel()
        embed = discord.Embed(description=case)
        await send_formatted_message(
            channel,
            "See the source.",
            _deps(),
            embed_data={"embed": embed},
        )
        for _content, kwargs in channel.calls:
            delivered = kwargs.get("embed")
            if delivered is None:
                continue
            _assert_no_live_link(delivered.description or "", case, "embed description")


@pytest.mark.asyncio
async def test_long_inline_code_split_neutralises_the_url_in_each_chunk() -> None:
    """A split inside an inline code span must not expose its URL in a chunk."""
    channel = _RecordingChannel()
    message = "`https://evil.example/x" + ("A" * 3_000) + "`"

    await send_split_message(channel, message, _deps())

    assert len(channel.calls) >= 2
    for content, _kwargs in channel.calls:
        assert "https://evil.example" not in content
        _assert_no_live_link(content, message, "inline-code chunk")


def test_f1_mid_line_fence_neutralises_the_url() -> None:
    """A mid-line opener makes Discord's pairing uncertain, so the URL dies."""
    payload = ("line\n" * 80) + "https://evil.example/gift\n```\n"

    for case in ("intro ```\n```\n" + payload, "intro ```\n```python\n" + payload):
        sanitized = sanitize_for_discord(case)

        assert "https://evil.example/gift" not in sanitized
        assert "https://\u200bevil.example/gift" in sanitized


def test_several_urls_in_one_run_are_all_neutralised() -> None:
    """Every URL in a whitespace-free run gets the zero-width space."""
    for case in (
        "https://a.example/x)https://evil.example/gift",
        "?next=https://evil.example/x",
        "one,https://evil.example/x",
    ):
        sanitized = sanitize_for_discord(case)

        assert "https://" + ZERO_WIDTH_SPACE in sanitized
        assert "https://evil.example" not in sanitized


@pytest.mark.parametrize(
    ("name", "case"),
    FENCE_INNER_RUN_CASES,
    ids=[name for name, _case in FENCE_INNER_RUN_CASES],
)
def test_fence_with_an_inner_triple_run_neutralises_the_link(name: str, case: str) -> None:
    """A stray triple-backtick run inside a fence makes the whole text ordinary."""
    sanitized = sanitize_for_discord(case)

    assert "https://evil.example" not in sanitized
    assert "https://\u200bevil.example" in sanitized
    assert protected_code_regions(case) == []
    _assert_no_live_link(sanitized, case, name)


def test_tilde_fence_variant_neutralises_the_link() -> None:
    """A ~~~ fence is not code in Discord, so its link is neutralised."""
    case = "~~~\nfoo\n~~~bar [x](https://evil.example/c)\n~~~\n"

    sanitized = sanitize_for_discord(case)

    assert protected_code_regions(case) == []
    assert "https://evil.example" not in sanitized
    assert "https://\u200bevil.example" in sanitized
    _assert_no_live_link(sanitized, case, "tilde fence")


def test_tilde_run_inside_a_backtick_fence_stays_protected() -> None:
    """Only a three-character backtick run disqualifies a fence, not ~~~."""
    case = "```\nfoo\n~~~bar [x](https://evil.example/c)\n```\n"

    assert sanitize_for_discord(case) == case


@pytest.mark.parametrize("content", ["``", "`"])
def test_fence_with_only_short_backtick_runs_stays_protected(content: str) -> None:
    """One or two backticks inside a fence are content, not a disqualifying run."""
    case = f"```\n{content}\n[x](https://evil.example/e)\n```\n"

    assert protected_code_regions(case)
    assert sanitize_for_discord(case) == case


def test_closed_fence_with_link_syntax_is_delivered_unchanged() -> None:
    """A clean closed fence keeps its link-like syntax because both parsers see code."""
    case = "```py\nx = '[a](https://ok.example)'\n```\ntext"

    assert sanitize_for_discord(case) == case


@pytest.mark.parametrize(
    ("name", "case"),
    INLINE_DIVERGENCE_CASES,
    ids=[name for name, _case in INLINE_DIVERGENCE_CASES],
)
def test_inline_span_that_discord_ends_elsewhere_is_not_protected(
    name: str,
    case: str,
) -> None:
    """CommonMark may pair backticks differently; the filter protects less."""
    oracle_urls = _discord_urls_outside_code(case)
    assert oracle_urls, f"{name}: the Discord oracle saw no URL outside code"

    sanitized = sanitize_for_discord(case)

    assert "https://evil.example" not in sanitized
    assert "https://\u200bevil.example" in sanitized
    assert protected_code_regions(case) == []
    _assert_no_live_link(sanitized, case, name)


@pytest.mark.asyncio
async def test_long_clean_fence_is_closed_and_reopened_across_chunks() -> None:
    """A fence with no inner run is still split with balanced markers."""
    channel = _RecordingChannel()
    message = "```py\n" + ("x = 1\n" * 400) + "```\n"

    await send_split_message(channel, message, _deps())

    assert len(channel.calls) >= 2
    for content, _kwargs in channel.calls[:-1]:
        assert content.endswith("```")
    for content, _kwargs in channel.calls[1:]:
        assert content.startswith("```py")
    assert all(content.count("```") % 2 == 0 for content, _kwargs in channel.calls)


@pytest.mark.parametrize(("name", "case"), NAMED_CASES, ids=[name for name, _case in NAMED_CASES])
def test_named_case_is_sanitised(name: str, case: str) -> None:
    """Each reported sanitiser case is neutralised in the delivered text."""
    sanitized = sanitize_for_discord(case)
    _assert_no_live_link(sanitized, case, name)


@pytest.mark.parametrize("depth", NESTED_DEPTHS)
def test_nested_labels_are_neutralised_at_every_depth(depth: int) -> None:
    """Every '](' is broken even when the parser only reports an inner label."""
    case = "[" * depth + "a" + "]" * depth + "(https://evil.example/x)"

    sanitized = sanitize_for_discord(case)

    _assert_no_live_link(sanitized, case, f"nested depth {depth}")


def test_f2_lines_are_kept_and_their_urls_are_neutralised() -> None:
    """A definition-shaped line is ordinary text, never an empty message."""
    warning = "[Warning]: do not run it as root."
    sources = "Sources:\n[1]: https://en.wikipedia.org/wiki/Paris"

    warning_output = sanitize_for_discord(warning)
    sources_output = sanitize_for_discord(sources)

    assert warning_output == warning
    assert "Sources:" in sources_output
    assert "[1]:" in sources_output
    assert "https://\u200ben.wikipedia.org/wiki/Paris" in sources_output
    assert "\n[1]: https://" not in sources_output


def test_closed_three_backtick_fence_is_delivered_unchanged() -> None:
    """A closed fence with exact markers keeps link-like syntax and URLs."""
    case = "```\nhandlers[0](event)\ncurl -s https://api.github.com/x\n```"

    assert sanitize_for_discord(case) == case


def test_unclosed_fence_and_indented_code_do_not_protect_a_link() -> None:
    """Only a closed exact fence protects; unclosed and indented blocks do not."""
    unclosed = "```\n[x](https://evil.example/d)"
    indented = "text\n\n    [x](https://evil.example/e)\n"

    for case in (unclosed, indented):
        sanitized = sanitize_for_discord(case)
        assert "](https://" not in sanitized
        assert "https://\u200bevil.example" in sanitized


def test_nul_characters_are_not_used_as_placeholder_tokens() -> None:
    """Model output cannot forge an internal marker because none exists."""
    case = "a\x00SAFE0\x00 `code` [x](https://evil.example/g)"

    sanitized = sanitize_for_discord(case)

    assert "SAFE0" in sanitized
    assert "https://evil.example/g" not in sanitized


def _repeat(unit: str, size: int) -> str:
    """Repeat ``unit`` to exactly ``size`` characters for a scaling shape."""
    return (unit * (size // len(unit) + 1))[:size]


def _oversized_shape(size: int) -> str:
    """Build a cheap oversized answer with a fence pair and a distant URL."""
    prefix = "```a```b " * 4
    suffix = " https://e"
    return prefix + "X" * (size - len(prefix) - len(suffix)) + suffix


COMPLEXITY_SHAPES = [
    lambda size: "`" * size,
    lambda size: "\\" * (size // 2) + "`" * (size // 2),
    lambda size: "x" * 2_100 + "`" * (size - 2_100),
    lambda size: _repeat("[`", size),
    lambda size: _repeat("<https://", size),
    lambda size: _repeat("[a[b", size),
    lambda size: _repeat("[a](https://e", size),
    lambda size: _repeat("](", size),
    lambda size: _repeat("``` ", size),
    lambda size: _repeat("```\n", size),
    lambda size: _repeat("```a```b", size),
    lambda size: _repeat("text ```x``` more\n", size),
    lambda size: "```\n" + "`" * (size - 4),
]


async def _delivery_parse_stats(shape: str) -> dict[str, int]:
    """Return the parser work for one sanitise-and-deliver run of ``shape``."""
    message_splitter._reset_parse_stats()
    sanitize_for_discord(shape)
    channel = _RecordingChannel()
    await send_formatted_message(channel, shape, _deps())
    return message_splitter._parse_stats()


@pytest.mark.asyncio
async def test_sanitise_and_deliver_are_not_superlinear() -> None:
    """Doubling the input must not more than double the parser work.

    The assertion counts bytes passed to ``Parser.parse`` and the number of
    parse calls, not wall-clock seconds: a shared two-core CI machine makes
    elapsed-time budgets flaky even when the code is linear. Every adversarial
    shape is built at 32,000 and 64,000 characters. The 64,000-character run
    may use 2.5 times the 32,000-character run's parser bytes plus a small
    fixed constant, and at most three times its parse calls plus two. Both
    bounds are work counters, so they measure the code rather than the host.

    Revert check: making the sanitiser parse the whole input once per 1,024
    bytes fails the bytes assertion because the counted work then grows with
    the square of the input length.
    """
    for shape in COMPLEXITY_SHAPES:
        smaller = shape(32_000)
        larger = shape(64_000)
        smaller_stats = await _delivery_parse_stats(smaller)
        larger_stats = await _delivery_parse_stats(larger)
        assert larger_stats["bytes"] <= 2.5 * smaller_stats["bytes"] + 4096, (
            f"{larger_stats['bytes']} parser bytes for {len(larger)} characters "
            f"vs {smaller_stats['bytes']} for {len(smaller)}"
        )
        assert larger_stats["calls"] <= 3 * smaller_stats["calls"] + 2, (
            f"{larger_stats['calls']} parse calls for {len(larger)} characters "
            f"vs {smaller_stats['calls']} for {len(smaller)}"
        )


@pytest.mark.asyncio
async def test_oversized_delivery_is_capped_before_parsing(monkeypatch) -> None:
    """A 128k or 256k answer is truncated by the work cap and stays fast."""
    original_parse = message_splitter._parse_markdown
    parsed_lengths: list[int] = []

    def recording_parse(text: str, **kwargs):
        parsed_lengths.append(len(text))
        return original_parse(text, **kwargs)

    monkeypatch.setattr(message_splitter, "_parse_markdown", recording_parse)

    for size in (128_000, 256_000):
        parsed_lengths.clear()
        shape = _oversized_shape(size)
        logger = MagicMock()
        channel = _RecordingChannel()
        started = time.perf_counter()
        await send_formatted_message(channel, shape, {"logger": logger})
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0, f"{elapsed:.2f}s for {size} characters"
        assert parsed_lengths
        assert max(parsed_lengths) <= 100_000
        assert len(channel.calls) == 50
        assert all(len(content) <= 2000 for content, _kwargs in channel.calls)
        assert "truncated" in channel.calls[-1][0].lower()
        assert str(size) in channel.calls[-1][0]
        logger.error.assert_called_once_with(
            "Message split reached chunk cap (%d) for message length %d",
            50,
            size,
        )


def test_trusted_citation_link_stays_clickable() -> None:
    """The allowlist still keeps its one link while everything else is inert."""
    trusted = "https://good.example/source"
    case = f"See [the docs]({trusted}) and [bad](https://evil.example/x)."

    sanitized = sanitize_for_discord(case, {"1": trusted})

    assert f"[the docs]({trusted})" in sanitized
    assert "https://evil.example/x" not in sanitized
    assert f'href="{trusted}"' in MARKDOWN.render(sanitized)


def test_delivery_is_repeatable_after_sanitising() -> None:
    """Sanitising an already-sanitised answer does not change it again."""
    for case in CORPUS[:200]:
        once = sanitize_for_discord(case)
        assert sanitize_for_discord(once) == once


def test_escaped_inline_closer_is_not_a_protected_region() -> None:
    """A parsed span whose closing backtick is escaped protects nothing."""
    text = "`a\\` [x](https://evil.example/e)`"

    assert protected_code_regions(text) == []
