"""Differential tests for the hand-written link sanitiser.

CommonMark is the oracle: after sanitisation, an independent parser must not
render a link. Code that the oracle renders as code may keep link-like syntax;
a link that survives outside code is a failure.
"""

import random
from unittest.mock import AsyncMock, MagicMock

import discord
from markdown_it import MarkdownIt
import pytest

from src.message_splitter import (
    sanitize_for_discord,
    sanitize_model_output,
    send_formatted_message,
)

MARKDOWN = MarkdownIt("commonmark")

KNOWN_CASES = [
    "`x\\` [Claim your Nitro](https://evil.example/gift) `",
    "[`a](https://evil.example/b)`",
    "[`Claim`](https://evil.example/c)",
    "```\n[x](https://evil.example/d)",
    "\\`[x](https://evil.example/e)\\`",
    "<https://evil.example/f>",
    "[a][1]\n\n[1]: https://evil.example/g",
]

FRAGMENTS = [
    "`",
    "``",
    "```",
    "````",
    "\\",
    "\\\\",
    "[x]",
    "[x][1]",
    "[a [b] c]",
    "(https://evil.example/x)",
    "<https://evil.example/y>",
    "[1]: https://evil.example/z",
    "\n",
    " ",
    "text",
    "`code`",
    "``code``",
    "[`a`](https://evil.example/b)",
    "\\`",
    "\n```\n",
    "\n````\n",
    "\n```\n",
    "@everyone",
    "@here",
    "<@1>",
    "<@&1>",
    "<#1>",
    "[label][missing]",
    "![image](https://evil.example/image)",
]

MENTIONS = ("@everyone", "@here", "<@1>", "<@&1>", "<#1>")


def _generated_cases(count: int = 360) -> list[str]:
    """Return a fixed-seed corpus of adversarial Markdown combinations."""
    generator = random.Random(20261123)  # noqa: S311 - fixed seed, not cryptography
    return [
        "".join(generator.choice(FRAGMENTS) for _ in range(generator.randint(3, 9)))
        for _ in range(count)
    ]


CORPUS = [*KNOWN_CASES, *_generated_cases()]


def _assert_no_rendered_link(sanitized: str, source: str, where: str) -> None:
    rendered = MARKDOWN.render(sanitized)
    assert "<a " not in rendered, f"{where} rendered a link from {source!r}: {rendered!r}"
    for mention in MENTIONS:
        assert mention not in sanitized, f"{where} kept {mention!r} from {source!r}"


def test_known_adversarial_inputs_have_no_rendered_link() -> None:
    """The reported bypass and its neighbouring delimiter cases stay inert."""
    for case in KNOWN_CASES:
        _assert_no_rendered_link(sanitize_model_output(case), case, "message")


def test_generated_markdown_corpus_has_no_rendered_link() -> None:
    """A fixed-seed corpus cannot smuggle an anchor past the sanitiser."""
    assert len(_generated_cases()) >= 300
    for case in CORPUS:
        _assert_no_rendered_link(sanitize_model_output(case), case, "message")


def test_trusted_citation_link_is_still_rendered_after_sanitising() -> None:
    """The oracle must see the one link the allowlist is meant to keep clickable."""
    trusted = "https://good.example/source"
    text = f"See [the docs]({trusted})."

    sanitized = sanitize_for_discord(text, {"1": trusted})

    assert f"[the docs]({trusted})" in sanitized
    assert f'href="{trusted}"' in MARKDOWN.render(sanitized)


@pytest.mark.asyncio
async def test_generated_markdown_corpus_is_safe_in_embed_descriptions() -> None:
    """The embed description path applies the same CommonMark-safe rule."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    deps = {"logger": MagicMock()}

    for case in CORPUS:
        embed = discord.Embed(description=case)

        await send_formatted_message(
            channel,
            "See the source.",
            deps,
            embed_data={"embed": embed},
        )

        delivered = channel.send.await_args.kwargs["embed"]
        _assert_no_rendered_link(delivered.description or "", case, "embed")
