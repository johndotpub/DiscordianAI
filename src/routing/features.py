"""Text views and unweighted routing cues."""

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
import re
import unicodedata
from urllib.parse import urlsplit

from .contracts import EvidenceClass, Route, Source
from .lexicon import Lexicon
from .scoring import STRUCTURAL_WEIGHTS

SOURCE_EXTENSIONS = frozenset(
    {
        "astro",
        "bash",
        "bat",
        "c",
        "cc",
        "cfg",
        "cjs",
        "clj",
        "cljs",
        "cmake",
        "cmd",
        "conf",
        "cpp",
        "cs",
        "css",
        "cxx",
        "dart",
        "dockerfile",
        "env",
        "erl",
        "ex",
        "exs",
        "fish",
        "go",
        "gql",
        "gradle",
        "graphql",
        "h",
        "hh",
        "hpp",
        "hrl",
        "htm",
        "html",
        "ini",
        "ipynb",
        "java",
        "jl",
        "js",
        "json",
        "jsonl",
        "jsx",
        "kt",
        "kts",
        "less",
        "lock",
        "lua",
        "m",
        "makefile",
        "md",
        "mjs",
        "mm",
        "php",
        "pl",
        "pm",
        "proto",
        "ps1",
        "py",
        "pyi",
        "pyw",
        "pyx",
        "r",
        "rb",
        "rs",
        "rst",
        "sass",
        "scala",
        "scss",
        "sh",
        "sql",
        "svelte",
        "swift",
        "toml",
        "ts",
        "tsx",
        "vue",
        "xml",
        "yaml",
        "yml",
        "zsh",
    }
)
_MIN_SUFFIX_LENGTH = 2
_MAX_SUFFIX_LENGTH = 24
_MAX_FILENAME_TOKEN_LENGTH = 64
_KNOWN_SUFFIXES = frozenset(
    {
        "ai",
        "app",
        "at",
        "au",
        "be",
        "biz",
        "blog",
        "br",
        "ca",
        "cc",
        "ch",
        "cloud",
        "cn",
        "co",
        "com",
        "de",
        "dev",
        "dk",
        "edu",
        "es",
        "eu",
        "fi",
        "fr",
        "gov",
        "gr",
        "hk",
        "id",
        "ie",
        "il",
        "in",
        "info",
        "io",
        "it",
        "jp",
        "kr",
        "ly",
        "me",
        "mx",
        "my",
        "net",
        "news",
        "nl",
        "no",
        "nz",
        "online",
        "org",
        "pe",
        "ph",
        "pl",
        "pt",
        "ru",
        "se",
        "sg",
        "sh",
        "site",
        "so",
        "store",
        "tech",
        "th",
        "to",
        "tr",
        "tv",
        "tw",
        "uk",
        "us",
        "vn",
        "wiki",
        "xyz",
        "za",
    }
)
_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u2032": "'",
    }
)
_CONTRACTIONS = {
    "what's": "what is",
    "who's": "who is",
    "when's": "when is",
    "where's": "where is",
    "why's": "why is",
    "how's": "how is",
    "that's": "that is",
    "it's": "it is",
    "he's": "he is",
    "she's": "she is",
    "there's": "there is",
    "here's": "here is",
    "let's": "let us",
    "i'm": "i am",
    "i've": "i have",
    "i'll": "i will",
    "i'd": "i would",
    "you're": "you are",
    "you've": "you have",
    "you'll": "you will",
    "we're": "we are",
    "they're": "they are",
    "they've": "they have",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "can't": "can not",
    "couldn't": "could not",
    "shouldn't": "should not",
    "wouldn't": "would not",
    "won't": "will not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
}
_CONTRACTION_PATTERN = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(re.escape(term) for term in sorted(_CONTRACTIONS, key=len, reverse=True))
    + r")(?![a-z0-9])"
)
_WHITESPACE = re.compile(r"\s+")


def _joined(*parts: str) -> str:
    return "".join(parts)


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_URL_CANDIDATE_PATTERN = re.compile(r"(?<!\S)\S*\.\S*")
_FENCE_PATTERN = re.compile(r"```(?:.*?```|.*\Z)", re.DOTALL)
_DOT_LETTER_PATTERN = re.compile(r"\.[A-Za-z]")
_FILENAME_PATTERN = re.compile(
    r"(?<![\w./\\-])[\w./\\-]{1,"
    + str(_MAX_FILENAME_TOKEN_LENGTH)
    + r"}\.(?:"
    + "|".join(sorted(SOURCE_EXTENSIONS, key=len, reverse=True))
    + r")(?![\w])",
    re.IGNORECASE,
)
_TRACEBACK_PATTERN = re.compile(
    _joined(
        r"(?im)^\s*traceback \(most recent call last\):",
        r'|^\s*file "[^"]+", line \d+',
    )
)
_EVENT_PATTERN = re.compile(
    r"\b(?:what (?:happened|is new|is going on|has changed)"
    r"|any (?:updates?|news)|latest (?:updates?|news))\b"
)
_VERSION_PATTERN = re.compile(
    _joined(
        r"(?<![a-z0-9])(?:v\d+(?:\.\d+)+(?:[-+][a-z0-9.-]+)?",
        r"|version\s+\d+(?:\.\d+)*",
        r"|\d{1,4}\.\d{1,3}(?:\.\d{1,4})*)(?![a-z0-9.])",
    )
)
_MONEY_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?"
    r"(?:\s?(?:k|m|b|bn|million|billion|trillion))?"
    r"|\d[\d,]*(?:\.\d+)?\s?"
    r"(?:usd|eur|gbp|jpy|cad|aud|dollars?|euros?|pounds?|cents?))"
    r"(?![a-z0-9])"
)
_YEAR_PATTERN = re.compile(r"(?<![a-z0-9])\d{4}(?![a-z0-9])")
_DEIXIS_PATTERN = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|now|currently|current|latest"
    r"|recently|this (?:week|month|year|morning|afternoon|evening)"
    r"|next (?:week|month|year)|last (?:night|week|month|year))\b"
)
_OPINION_PATTERN = re.compile(
    r"\b(?:i (?:think|believe|feel|reckon)|in my opinion|do you think"
    r"|what do you think|which is better|better than|favorite|favourite"
    r"|should i|worth it)\b"
)
_CREATIVE_PATTERN = re.compile(
    r"\b(?:write|tell me|compose|imagine|brainstorm)\b[^.!?\n]{0,40}"
    r"\b(?:story|poem|song|essay|joke|haiku|lyrics|fiction|script|tale)\b"
    r"|\broleplay\b|\bfiction\b"
)
_NARRATIVE_PATTERN = re.compile(
    r"\bi\s+(?:spoke|went|saw|met|talked|called|visited|ate|read"
    r"|watched|heard|did|had|was)\b[^.!?\n]{0,80}"
    r"\b(?:yesterday|last (?:night|week|month|year)|ago"
    r"|this (?:morning|afternoon|evening))\b"
)
_LOOKUP_PATTERN = re.compile(
    r"\b(?:look up|lookup|search for|find out|google|what is|who is" + r"|tell me about)\b"
)
_SUPPLIED_ARTEFACT_PATTERN = re.compile(
    r"(?:"
    r"^\s*summari[sz]e\s*:"
    r"|^\s*summari[sz]e\s+(?:this|these|the following|the above|below)\b"
    r"|\btl;dr\b"
    r"|\bturn these\b[^.\n]{0,30}\bnotes into\b"
    r"|\bturn this into\b"
    r"|\bthese\b(?:\s+\w+){0,3}\s+notes\b"
    r"|\bthis\b(?:\s+\w+){0,2}\s+(?:log|error|json|changelog|paragraph)\b"
    r"|\bwhat(?: is|s)? this saying\b"
    r"|\bshould the\b[^.!?\n]{1,80}\bbe\b"
    r"|\bin our schema\b"
    r")"
)
_IN_PLAIN_ENGLISH_PATTERN = re.compile(r"\bin plain english\b")
_SUPPLIED_MARKERS = (
    "summar",
    "tl;dr",
    "turn this",
    "turn these",
    "these",
    "this",
    "what",
    "should the",
    "in our schema",
    "plain english",
)
_QUOTED_BLOCK_PATTERN = re.compile(
    r"```.*?```|(?:^|\n)\s*>|[\"“][^\"”\n]{4,}[\"”]|'[^'\n]{4,}'|`[^`\n]{4,}`",
    re.DOTALL,
)
_DURATION_PATTERN = re.compile(
    r"\b(?:a couple of|a few|\d+(?:\.\d+)?|an?|one|two|three|four|five|six"
    r"|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty"
    r"|sixty|seventy|eighty|ninety|hundred)\s+"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b"
)
_SUPPLIED_CANCELLED_CLASSES = frozenset({"volatile_topic", "change_verb"})
_EXPLICIT_ROUTE_PREFIXES: dict[str, tuple[Route, str | None]] = {
    "!web": ("web", None),
    "?web": ("web", None),
    "!local": ("local", None),
    "?status": ("web", "status"),
    "?price": ("web", "price"),
    "?release": ("web", "release"),
    "?news": ("web", "news"),
}
_EXPLICIT_PREFIX_PATTERN = re.compile(r"^([!?])([a-z]+)\s+")
_ENTITY_WORD = r"[A-Z][a-z]+(?:['\u2019-][A-Z][a-z]+)?"
_ENTITY_PATTERN = re.compile(rf"\b{_ENTITY_WORD}(?:\s+{_ENTITY_WORD})*\b")
_QUESTION_WORDS = frozenset(
    {"what", "who", "when", "where", "why", "how", "which", "whose", "whom"}
)
_AUXILIARIES = frozenset(
    {
        "am",
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "was",
        "were",
        "will",
        "would",
    }
)
_IMPERATIVE_VERBS = frozenset(
    {
        "add",
        "build",
        "calculate",
        "check",
        "close",
        "compare",
        "create",
        "debug",
        "delete",
        "describe",
        "explain",
        "fetch",
        "find",
        "fix",
        "generate",
        "get",
        "give",
        "help",
        "install",
        "list",
        "look",
        "make",
        "open",
        "optimize",
        "refactor",
        "remove",
        "review",
        "run",
        "search",
        "show",
        "summarize",
        "tell",
        "test",
        "translate",
        "update",
        "write",
    }
)
_COPULAS = frozenset(
    {
        "am",
        "appear",
        "appeared",
        "appears",
        "are",
        "be",
        "became",
        "become",
        "becomes",
        "been",
        "being",
        "feel",
        "feels",
        "felt",
        "get",
        "gets",
        "go",
        "goes",
        "got",
        "is",
        "look",
        "looked",
        "looks",
        "remain",
        "remained",
        "remains",
        "seem",
        "seemed",
        "seems",
        "stay",
        "stayed",
        "stays",
        "turn",
        "turned",
        "turns",
        "was",
        "went",
        "were",
    }
)
_ENTITY_STOPWORDS = frozenset(
    {
        "are",
        "best",
        "can",
        "cheers",
        "congrats",
        "could",
        "did",
        "do",
        "does",
        "done",
        "evening",
        "explain",
        "find",
        "give",
        "good",
        "goodnight",
        "hello",
        "help",
        "hey",
        "hi",
        "how",
        "is",
        "list",
        "make",
        "morning",
        "nice",
        "please",
        "regards",
        "search",
        "show",
        "sorry",
        "tell",
        "thank",
        "thanks",
        "that",
        "the",
        "this",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "work",
        "would",
        "write",
    }
)
_SIGNAL_BY_CLASS: dict[str, tuple[str, EvidenceClass]] = {
    "state_adjective": ("pred.status", "bearing"),
    "change_verb": ("pred.change", "bearing"),
    "outcome_verb": ("pred.outcome", "bearing"),
    "volatile_topic": ("topic.volatile", "bearing"),
    "release_state": ("pred.release", "bearing"),
    "commerce": ("topic.commerce", "bearing"),
    "incumbency": ("topic.incumbency", "bearing"),
    "version_currency": ("topic.version_currency", "bearing"),
    "encyclopedic_relation": ("frame.bounded_relation", "framing"),
    "social_only": ("frame.social_only", "framing"),
    "greeting": ("frame.greeting", "framing"),
    "local_context": ("neg.env", "framing"),
}


@dataclass(frozen=True, slots=True)
class TextViews:
    """Parallel surface and folded text with a folded-to-surface span map."""

    surface: str
    folded: str
    origin: tuple[tuple[int, int], ...]

    def surface_span(self, start: int, end: int) -> tuple[int, int]:
        """Translate a folded half-open span into a surface half-open span."""
        if not self.origin:
            return (0, 0)
        start = max(0, min(start, len(self.origin)))
        end = max(0, min(end, len(self.origin)))
        if start >= end:
            point = self.origin[start][0] if start < len(self.origin) else len(self.surface)
            return (point, point)
        return (self.origin[start][0], self.origin[end - 1][1])


@dataclass(frozen=True, slots=True)
class Cue:
    """A routing cue carrying its family base weight before saturation."""

    signal: str
    klass: EvidenceClass
    span: tuple[int, int] | None
    detail: str
    source: Source = "structural"
    weight: float = 0.0


@dataclass(frozen=True, slots=True)
class ExplicitRoute:
    """A control prefix that forces a route before any scoring happens."""

    route: Route
    class_hint: str | None = None


def parse_explicit_route(text: str) -> tuple[ExplicitRoute | None, str]:
    """Parse a leading control prefix and return the text that remains.

    The prefix must be at position zero, lowercase, and followed by
    whitespace. An unknown or malformed prefix is ordinary text and is
    returned unchanged.
    """
    match = _EXPLICIT_PREFIX_PATTERN.match(text)
    if match is None:
        return None, text
    token = f"{match.group(1)}{match.group(2)}"
    spec = _EXPLICIT_ROUTE_PREFIXES.get(token)
    if spec is None:
        return None, text
    route, class_hint = spec
    return ExplicitRoute(route=route, class_hint=class_hint), text[match.end() :].lstrip()


def views(text: str) -> TextViews:
    """Build offset-mapped surface and folded views of ``text``."""
    if text.isascii() and "'" not in text:
        return TextViews(
            surface=text,
            folded=text.lower(),
            origin=_identity_origin(len(text)),
        )
    if text.isascii():
        preliminary_text = text.lower()
        preliminary_origin = [(index, index + 1) for index in range(len(text))]
    else:
        preliminary: list[str] = []
        preliminary_origin = []
        index = 0
        while index < len(text):
            end = index + 1
            while end < len(text) and unicodedata.combining(text[end]):
                end += 1
            folded_cluster = unicodedata.normalize(
                "NFKC", text[index:end].translate(_APOSTROPHES)
            ).lower()
            for output in folded_cluster:
                preliminary.append(output)
                preliminary_origin.append((index, end))
            index = end
        preliminary_text = "".join(preliminary)

    folded_chars: list[str] = []
    folded_origin: list[tuple[int, int]] = []
    cursor = 0
    for match in _CONTRACTION_PATTERN.finditer(preliminary_text):
        for position in range(cursor, match.start()):
            folded_chars.append(preliminary_text[position])
            folded_origin.append(preliminary_origin[position])
        contraction_length = match.end() - match.start()
        for offset, output in enumerate(_CONTRACTIONS[match.group(1)]):
            local_index = min(offset, contraction_length - 1)
            origin_span = preliminary_origin[match.start() + local_index]
            folded_chars.append(output)
            folded_origin.append(origin_span)
        cursor = match.end()
    for position in range(cursor, len(preliminary_text)):
        folded_chars.append(preliminary_text[position])
        folded_origin.append(preliminary_origin[position])

    return TextViews(
        surface=text,
        folded="".join(folded_chars),
        origin=tuple(folded_origin),
    )


@lru_cache(maxsize=64)
def _identity_origin(length: int) -> tuple[tuple[int, int], ...]:
    return tuple((index, index + 1) for index in range(length))


def mask_code(text: str) -> str:
    """Blank fenced blocks and source filenames while preserving every offset."""
    regions = _code_regions(text)
    if not regions:
        return text
    return _mask_regions(text, regions)


def is_url(token: str) -> bool:
    """Return True for a URL-shaped token, using a pragmatic suffix rule.

    A bundled public suffix list is out of scope. Bare hosts therefore need a
    common suffix from a small allowlist; only an explicit ``http``/``https``
    scheme accepts an arbitrary alphabetic final label. Source-code extensions
    and masked filenames never count, so ``main.py``, ``package.json`` and
    ``asyncio.gather`` are not URLs.
    """
    candidate = token.strip().strip(".,;:!?)]}>'\"")
    if not candidate or any(character.isspace() for character in candidate):
        return False

    if "://" in candidate:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        return _valid_host(parsed.hostname, require_known_suffix=False)

    host = re.split(r"[/?#]", candidate, maxsplit=1)[0]
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if ":" in host:
        host = host.rsplit(":", 1)[0]
    return _valid_host(host, require_known_suffix=True)


def extract_overrides(text_views: TextViews, lexicon: Lexicon) -> tuple[Cue, ...]:
    """Return explicit instruction and URL override cues."""
    cues: list[Cue] = []
    for kind in sorted(lexicon.overrides):
        for pattern in lexicon.overrides[kind]:
            cues.extend(
                Cue(
                    signal=f"override.{kind}",
                    klass="override",
                    span=text_views.surface_span(match.start(), match.end()),
                    detail=match.group(),
                    source="override",
                )
                for match in pattern.finditer(text_views.folded)
            )

    for match in _URL_CANDIDATE_PATTERN.finditer(text_views.surface):
        token = match.group().strip(".,;:!?)]}>'\"")
        if token and is_url(token):
            cues.append(
                Cue(
                    signal="override.url",
                    klass="override",
                    span=(match.start(), match.end()),
                    detail=token,
                    source="override",
                )
            )
    return _sorted_cues(cues)


def extract_cues(
    views: TextViews,
    lexicon: Lexicon,
    *,
    clock: Callable[[], date] | None = None,
) -> tuple[Cue, ...]:
    """Return the unweighted bearing and framing cues in ``views``."""
    cues: list[Cue] = []
    folded = views.folded
    surface = views.surface
    code_regions = _code_regions(surface)
    masked = _mask_regions(surface, code_regions) if code_regions else surface
    tokens = _tokens(folded)

    def add(
        signal: str,
        klass: EvidenceClass,
        span: tuple[int, int],
        detail: str,
        weight: float | None = None,
    ) -> None:
        cues.append(
            Cue(
                signal=signal,
                klass=klass,
                span=views.surface_span(span[0], span[1]),
                detail=detail,
                source="lexicon" if weight is not None else "structural",
                weight=STRUCTURAL_WEIGHTS.get(signal, 0.0) if weight is None else weight,
            )
        )

    cues.extend(_lexicon_cues(lexicon, views, tokens))

    _add_pattern(cues, views, _EVENT_PATTERN, ("pred.event", "bearing"))
    _add_pattern(cues, views, _VERSION_PATTERN, ("shape.version", "bearing"))
    _add_pattern(cues, views, _MONEY_PATTERN, ("shape.money", "bearing"))
    _add_pattern(cues, views, _DEIXIS_PATTERN, ("time.deixis", "bearing"))

    current_year = (clock or date.today)().year
    for match in _YEAR_PATTERN.finditer(folded):
        if int(match.group()) >= current_year - 1:
            add("time.year", "bearing", match.span(), match.group())

    if tokens and (tokens[0][0] in _QUESTION_WORDS or tokens[0][0] in _AUXILIARIES):
        add("frame.question", "framing", (tokens[0][1], tokens[0][2]), tokens[0][0])
    elif folded.rstrip().endswith("?"):
        add(
            "frame.question",
            "framing",
            (max(0, len(folded) - 1), len(folded)),
            "?",
        )

    verb_index = 1 if len(tokens) > 1 and tokens[0][0] == "please" else 0
    if tokens and tokens[verb_index][0] in _IMPERATIVE_VERBS:
        add(
            "frame.imperative",
            "framing",
            (tokens[verb_index][1], tokens[verb_index][2]),
            tokens[verb_index][0],
        )

    _add_pattern(cues, views, _OPINION_PATTERN, ("frame.opinion", "framing"))
    _add_pattern(cues, views, _CREATIVE_PATTERN, ("frame.creative", "framing"))
    _add_pattern(cues, views, _NARRATIVE_PATTERN, ("neg.narrative", "framing"))
    _add_pattern(cues, views, _LOOKUP_PATTERN, ("cue.lookup", "framing"))

    for match in _ENTITY_PATTERN.finditer(masked):
        first_word = match.group().split()[0].lower()
        if first_word in _ENTITY_STOPWORDS or is_url(match.group()):
            continue
        add("ref.entity", "framing", match.span(), match.group())

    for start, end, kind in code_regions:
        add("code.shape", "framing", (start, end), kind)
    for match in _TRACEBACK_PATTERN.finditer(surface):
        add("code.shape", "framing", match.span(), "traceback")

    cues = _suppress_declarative_incumbency(cues)

    has_other_bearing = any(cue.klass == "bearing" and cue.signal != "time.deixis" for cue in cues)
    question_present = any(cue.signal == "frame.question" for cue in cues)
    if not has_other_bearing and not question_present:
        cues = [
            (
                replace(
                    cue,
                    klass="framing",
                    weight=STRUCTURAL_WEIGHTS["time.deixis.framing"],
                )
                if cue.signal == "time.deixis"
                else cue
            )
            for cue in cues
        ]

    return _sorted_cues(cues)


def _lexicon_cues(
    lexicon: Lexicon,
    views: TextViews,
    tokens: tuple[tuple[str, int, int], ...],
) -> list[Cue]:
    folded = views.folded
    token_starts = tuple(token[1] for token in tokens)
    supplied_spans = _supplied_artefact_spans(views)
    duration_spans = _duration_spans(folded) if "hour" in folded else ()
    cues: list[Cue] = []
    for hit in lexicon.find(folded):
        if supplied_spans and hit.term.class_name in _SUPPLIED_CANCELLED_CLASSES:
            continue
        if hit.term.class_name == "volatile_topic" and _overlaps(hit.span, duration_spans):
            continue
        if hit.term.class_name == "state_adjective" and not _has_copula_near(
            tokens, token_starts, hit.span
        ):
            continue
        signal, klass = _SIGNAL_BY_CLASS[hit.term.class_name]
        cues.append(
            Cue(
                signal=signal,
                klass=klass,
                span=views.surface_span(hit.span[0], hit.span[1]),
                detail=hit.term.text,
                source="lexicon",
                weight=lexicon.class_weights[hit.term.class_name],
            )
        )
    cues.extend(
        Cue(
            signal="neg.supplied_artifact",
            klass="local",
            span=views.surface_span(span[0], span[1]),
            detail="artifact",
            source="structural",
            weight=STRUCTURAL_WEIGHTS["neg.supplied_artifact"],
        )
        for span in supplied_spans
    )
    return cues


def _supplied_artefact_spans(views: TextViews) -> tuple[tuple[int, int], ...]:
    if not any(marker in views.folded for marker in _SUPPLIED_MARKERS):
        return ()
    spans = {match.span() for match in _SUPPLIED_ARTEFACT_PATTERN.finditer(views.folded)}
    if _IN_PLAIN_ENGLISH_PATTERN.search(views.folded) and _QUOTED_BLOCK_PATTERN.search(
        views.surface
    ):
        spans.update(match.span() for match in _IN_PLAIN_ENGLISH_PATTERN.finditer(views.folded))
    return tuple(sorted(spans))


def _duration_spans(folded: str) -> tuple[tuple[int, int], ...]:
    return tuple(match.span() for match in _DURATION_PATTERN.finditer(folded))


def _overlaps(span: tuple[int, int], regions: tuple[tuple[int, int], ...]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in regions)


def _suppress_declarative_incumbency(cues: list[Cue]) -> list[Cue]:
    incumbency = [cue for cue in cues if cue.signal == "topic.incumbency"]
    if not incumbency:
        return cues
    question_present = any(cue.signal == "frame.question" for cue in cues)
    other_bearing = any(
        cue.klass == "bearing" and cue.signal != "topic.incumbency" for cue in cues
    )
    if question_present or other_bearing:
        return cues
    return [cue for cue in cues if cue.signal != "topic.incumbency"]


def _add_pattern(
    cues: list[Cue],
    text_views: TextViews,
    pattern: re.Pattern[str],
    signal_klass: tuple[str, EvidenceClass],
    source: Source = "structural",
) -> None:
    signal, klass = signal_klass
    cues.extend(
        Cue(
            signal=signal,
            klass=klass,
            span=text_views.surface_span(match.start(), match.end()),
            detail=match.group(),
            source=source,
            weight=STRUCTURAL_WEIGHTS[signal],
        )
        for match in pattern.finditer(text_views.folded)
    )


def _sorted_cues(cues: list[Cue]) -> tuple[Cue, ...]:
    return tuple(
        sorted(
            cues,
            key=lambda cue: (
                cue.span[0] if cue.span else -1,
                cue.span[1] if cue.span else -1,
                cue.signal,
                cue.detail,
            ),
        )
    )


def _tokens(folded: str) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (match.group(), match.start(), match.end()) for match in _TOKEN_PATTERN.finditer(folded)
    )


def _has_copula_near(
    tokens: tuple[tuple[str, int, int], ...],
    token_starts: tuple[int, ...],
    span: tuple[int, int],
) -> bool:
    if not tokens:
        return False
    first_overlap = max(0, bisect_left(token_starts, span[0]) - 1)
    last_overlap = max(first_overlap, bisect_right(token_starts, span[1]) - 1)
    first = max(0, first_overlap - 4)
    last = min(len(tokens), last_overlap + 5)
    return any(tokens[index][0] in _COPULAS for index in range(first, last))


def _valid_host(host: str, *, require_known_suffix: bool) -> bool:
    host = host.lower().rstrip(".")
    if "." not in host:
        return False
    final = host.rsplit(".", 1)[1]
    if final in SOURCE_EXTENSIONS:
        return False
    if not final.isalpha() or not _MIN_SUFFIX_LENGTH <= len(final) <= _MAX_SUFFIX_LENGTH:
        return False
    return not require_known_suffix or final in _KNOWN_SUFFIXES


def _code_regions(text: str) -> tuple[tuple[int, int, str], ...]:
    if "```" not in text and _DOT_LETTER_PATTERN.search(text) is None:
        return ()
    fences = _merge_adjacent_regions(
        [(match.start(), match.end(), "fence") for match in _FENCE_PATTERN.finditer(text)]
    )
    masked = _mask_regions(text, fences)
    filenames = [
        (match.start(), match.end(), "filename") for match in _FILENAME_PATTERN.finditer(masked)
    ]
    return tuple(_merge_adjacent_regions([*fences, *filenames]))


def _merge_adjacent_regions(
    regions: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    merged: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(regions):
        if merged and kind == merged[-1][2] and start <= merged[-1][1]:
            previous_start, previous_end, _ = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end), kind)
            continue
        merged.append((start, end, kind))
    return merged


def _mask_regions(
    text: str, regions: tuple[tuple[int, int, str], ...] | list[tuple[int, int, str]]
) -> str:
    characters = list(text)
    for start, end, _kind in regions:
        for index in range(start, end):
            if characters[index] != "\n":
                characters[index] = " "
    return "".join(characters)
