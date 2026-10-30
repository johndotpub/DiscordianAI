"""Load, validate, and index the routing lexicon."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal
import unicodedata

TermClass = Literal["bearing", "framing"]

_SUPPORTED_VERSION = "1"
_SUPPORTED_LANGUAGE = "en"
_MIN_WEIGHT = -10.0
_MAX_WEIGHT = 10.0
_FUZZY_MIN_LENGTH = 4
_FUZZY_CACHE_MAX = 2048
_EVIDENCE_CLASSES = frozenset({"bearing", "framing"})
_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u2032": "'",
    }
)
_WHITESPACE = re.compile(r"\s+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_NEVER_MATCH = re.compile(r"(?!)")
_BUNDLED_PATH = Path(__file__).resolve().parent / "data" / "lexicon.en.json"
_FUZZY_EXCLUSIONS: dict[str, frozenset[str]] = {
    "change_verb": frozenset(
        {"change", "changes", "changing", "release", "releases", "releasing"}
    ),
    "outcome_verb": frozenset(
        {
            "acquire",
            "acquires",
            "acquiring",
            "note",
            "noted",
            "notes",
            "rule",
            "rules",
            "vite",
        }
    ),
    "release_state": frozenset({"rest", "rests"}),
    "volatile_topic": frozenset({"braking", "deadline", "deadlines", "headline", "wife", "wives"}),
}
# Fuzzy hits are excluded outright rather than given a reduced weight: any
# positive bearing weight can still decide a route on its own, while an exact
# hit is handled before this set is consulted. Short function words are never
# fuzzy-matched: at two letters an insertion or deletion turns one into another
# word (`on`/`won`, `to`/`cto`) long before it looks like a typo.
_FUZZY_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "again",
        "also",
        "and",
        "any",
        "are",
        "been",
        "before",
        "best",
        "but",
        "can",
        "could",
        "did",
        "does",
        "from",
        "had",
        "has",
        "have",
        "i",
        "last",
        "list",
        "new",
        "next",
        "now",
        "on",
        "should",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "u",
        "was",
        "were",
        "will",
        "with",
        "would",
        "your",
    }
)


class LexiconError(ValueError):
    """Raised when a lexicon file is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class Term:
    """A normalised term and the class that owns it."""

    text: str
    klass: TermClass
    class_name: str


@dataclass(frozen=True, slots=True)
class TermHit:
    """A term occurrence in a folded string."""

    term: Term
    span: tuple[int, int]
    fuzzy: bool = False


@dataclass(frozen=True, slots=True)
class Lexicon:
    """A validated lexicon with exact, fuzzy, and override matchers."""

    version: str
    language: str
    classes: Mapping[str, TermClass]
    class_weights: Mapping[str, float]
    terms: Mapping[str, tuple[Term, ...]]
    matchers: Mapping[str, re.Pattern[str]]
    overrides: Mapping[str, tuple[re.Pattern[str], ...]]
    fuzzy_index: Mapping[str, Mapping[str, tuple[str, ...]]] = field(repr=False, compare=False)
    fuzzy_terms: Mapping[str, tuple[Term, ...]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    term_lookups: Mapping[str, Mapping[str, Term]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    exact_words: frozenset[str] = field(
        default_factory=frozenset,
        repr=False,
        compare=False,
    )
    first_words: Mapping[str, frozenset[str]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _fuzzy_cache: dict[str, tuple[Term, ...]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Lexicon":
        """Load and validate a lexicon, defaulting to the bundled English file."""
        source = Path(path) if path is not None else _BUNDLED_PATH
        return cls._from_mapping(_read_mapping(source))

    def find(self, folded: str) -> tuple[TermHit, ...]:
        """Return exact hits plus permitted typo hits in ``folded``."""
        hits: list[TermHit] = []
        exact_keys: set[tuple[str, int, int]] = set()
        token_matches = tuple(_TOKEN_PATTERN.finditer(folded))
        token_set = {match.group() for match in token_matches}
        for class_name in sorted(self.matchers):
            triggers = self.first_words.get(class_name)
            if triggers is not None and token_set.isdisjoint(triggers):
                continue
            lookup = self.term_lookups.get(class_name)
            if lookup is None:
                lookup = {term.text: term for term in self.terms[class_name]}
            for match in self.matchers[class_name].finditer(folded):
                term = lookup.get(_WHITESPACE.sub(" ", match.group(0)))
                if term is None:
                    continue
                hits.append(TermHit(term=term, span=match.span()))
                exact_keys.add((class_name, match.start(), match.end()))

        exact_words = self.exact_words
        if not exact_words:
            exact_words = frozenset(
                term.text
                for class_terms in self.terms.values()
                for term in class_terms
                if " " not in term.text
            )
        for token_match in token_matches:
            token = token_match.group()
            if len(token) < _FUZZY_MIN_LENGTH or token in exact_words:
                continue
            for term in self._fuzzy_matches_folded(token):
                if token in _FUZZY_EXCLUSIONS.get(term.class_name, ()):
                    continue
                key = (term.class_name, token_match.start(), token_match.end())
                if key in exact_keys:
                    continue
                if any(
                    hit.term == term
                    and hit.span[0] <= token_match.start()
                    and hit.span[1] >= token_match.end()
                    for hit in hits
                ):
                    continue
                hits.append(TermHit(term=term, span=token_match.span(), fuzzy=True))

        return tuple(
            sorted(
                hits,
                key=lambda hit: (
                    hit.span[0],
                    hit.span[1],
                    hit.term.class_name,
                    hit.term.text,
                ),
            )
        )

    def fuzzy_matches(self, token: str) -> tuple[Term, ...]:
        """Return single-word terms reachable by a permitted typo of ``token``."""
        return self._fuzzy_matches_folded(_fold_term(token))

    def _fuzzy_matches_folded(self, folded: str) -> tuple[Term, ...]:
        cached = self._fuzzy_cache.get(folded)
        if cached is not None:
            return cached
        if (
            not folded
            or " " in folded
            or len(folded) < _FUZZY_MIN_LENGTH
            or folded in _FUZZY_STOPWORDS
        ):
            matches: tuple[Term, ...] = ()
        else:
            variants = {folded, *_deletions(folded)}
            candidates: set[Term] = set()
            for variant in variants:
                candidates.update(self.fuzzy_terms.get(variant, ()))

            matches = tuple(
                sorted(
                    (term for term in candidates if _is_permitted_fuzzy_edit(folded, term.text)),
                    key=lambda term: (term.class_name, term.text),
                )
            )
        if len(self._fuzzy_cache) < _FUZZY_CACHE_MAX:
            self._fuzzy_cache[folded] = matches
        return matches

    @classmethod
    def _from_mapping(cls, data: Mapping[str, object]) -> "Lexicon":
        version = _require_version(data)
        language = _require_language(data)
        classes_raw = data.get("classes")
        if not isinstance(classes_raw, Mapping):
            msg = "Lexicon key 'classes' must be an object"
            raise LexiconError(msg)

        classes, weights, terms, matchers, fuzzy_index, fuzzy_terms = _build_classes(classes_raw)
        overrides = _compile_overrides(data.get("overrides", {}))
        term_lookups = MappingProxyType(
            {
                name: MappingProxyType({term.text: term for term in class_terms})
                for name, class_terms in terms.items()
            }
        )
        exact_words = frozenset(
            term.text
            for class_terms in terms.values()
            for term in class_terms
            if " " not in term.text
        )
        first_words = MappingProxyType(
            {
                name: frozenset(term.text.split(" ", 1)[0] for term in class_terms)
                for name, class_terms in terms.items()
            }
        )
        return cls(
            version=version,
            language=language,
            classes=classes,
            class_weights=weights,
            terms=terms,
            matchers=matchers,
            overrides=overrides,
            fuzzy_index=fuzzy_index,
            fuzzy_terms=fuzzy_terms,
            term_lookups=term_lookups,
            exact_words=exact_words,
            first_words=first_words,
        )


def _read_mapping(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Could not read routing lexicon {path}: {exc}"
        raise LexiconError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = f"Routing lexicon {path} is not valid JSON: {exc}"
        raise LexiconError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"Routing lexicon {path} must contain a JSON object"
        raise LexiconError(msg)
    return raw


def _require_version(data: Mapping[str, object]) -> str:
    version = data.get("version")
    if version != _SUPPORTED_VERSION:
        msg = (
            f"Lexicon version {version!r} does not match supported "
            f"version {_SUPPORTED_VERSION!r}"
        )
        raise LexiconError(msg)
    return _SUPPORTED_VERSION


def _require_language(data: Mapping[str, object]) -> str:
    language = data.get("language")
    if language != _SUPPORTED_LANGUAGE:
        msg = (
            f"Lexicon language {language!r} is not supported "
            f"(expected {_SUPPORTED_LANGUAGE!r})"
        )
        raise LexiconError(msg)
    return _SUPPORTED_LANGUAGE


def _build_classes(
    classes_raw: Mapping[object, object],
) -> tuple[
    Mapping[str, TermClass],
    Mapping[str, float],
    Mapping[str, tuple[Term, ...]],
    Mapping[str, re.Pattern[str]],
    Mapping[str, Mapping[str, tuple[str, ...]]],
    Mapping[str, tuple[Term, ...]],
]:
    classes: dict[str, TermClass] = {}
    weights: dict[str, float] = {}
    terms_by_class: dict[str, tuple[Term, ...]] = {}
    matchers: dict[str, re.Pattern[str]] = {}
    fuzzy_indexes: dict[str, Mapping[str, tuple[str, ...]]] = {}
    seen_terms: dict[str, str] = {}

    for name in sorted(classes_raw, key=str):
        spec = classes_raw[name]
        if not isinstance(name, str) or not isinstance(spec, Mapping):
            msg = f"Lexicon class {name!r} must be an object"
            raise LexiconError(msg)

        klass_raw = spec.get("klass")
        if klass_raw not in _EVIDENCE_CLASSES:
            msg = f"Unknown class {klass_raw!r} in class {name!r}"
            raise LexiconError(msg)
        klass: TermClass = "bearing" if klass_raw == "bearing" else "framing"

        weight = _class_weight(name, spec.get("weight"))
        class_terms = _class_terms(name, klass, spec.get("terms"), seen_terms)

        classes[name] = klass
        weights[name] = weight
        terms_by_class[name] = class_terms
        matchers[name] = _compile_class_matcher(class_terms)
        fuzzy_indexes[name] = _build_fuzzy_index(class_terms)

    return (
        MappingProxyType(dict(sorted(classes.items()))),
        MappingProxyType(dict(sorted(weights.items()))),
        MappingProxyType(dict(sorted(terms_by_class.items()))),
        MappingProxyType(dict(sorted(matchers.items()))),
        MappingProxyType(dict(sorted(fuzzy_indexes.items()))),
        _combine_fuzzy_indexes(fuzzy_indexes, terms_by_class),
    )


def _class_weight(name: str, raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        msg = f"Class {name!r} weight {raw!r} must be a number"
        raise LexiconError(msg)
    weight = float(raw)
    if not _MIN_WEIGHT <= weight <= _MAX_WEIGHT:
        msg = f"Class {name!r} weight {weight} is outside [-10, 10]"
        raise LexiconError(msg)
    return weight


def _class_terms(
    name: str,
    klass: TermClass,
    raw: object,
    seen_terms: dict[str, str],
) -> tuple[Term, ...]:
    if not isinstance(raw, list):
        msg = f"Class {name!r} key 'terms' must be a list"
        raise LexiconError(msg)

    class_terms: list[Term] = []
    seen_here: set[str] = set()
    for raw_term in raw:
        if not isinstance(raw_term, str) or not raw_term.strip():
            msg = f"Class {name!r} term {raw_term!r} must be a non-empty string"
            raise LexiconError(msg)
        text = _fold_term(raw_term)
        if text in seen_here:
            continue
        owner = seen_terms.get(text)
        if owner is not None and owner != name:
            msg = f"Term {text!r} appears in both {owner!r} and {name!r}"
            raise LexiconError(msg)
        seen_terms[text] = name
        seen_here.add(text)
        class_terms.append(Term(text=text, klass=klass, class_name=name))

    return tuple(sorted(class_terms, key=lambda term: term.text))


def _compile_class_matcher(class_terms: Sequence[Term]) -> re.Pattern[str]:
    if not class_terms:
        return _NEVER_MATCH
    alternatives = sorted(
        {_term_pattern(term.text) for term in class_terms},
        key=lambda pattern: (-len(pattern), pattern),
    )
    return re.compile(r"(?<![a-z0-9])(" + "|".join(alternatives) + r")(?![a-z0-9])")


def _term_pattern(text: str) -> str:
    return r"\s+".join(re.escape(word) for word in text.split(" "))


def _combine_fuzzy_indexes(
    indexes: Mapping[str, Mapping[str, tuple[str, ...]]],
    terms_by_class: Mapping[str, tuple[Term, ...]],
) -> Mapping[str, tuple[Term, ...]]:
    lookup = {term.text: term for class_terms in terms_by_class.values() for term in class_terms}
    combined: dict[str, set[str]] = {}
    for index in indexes.values():
        for variant, texts in index.items():
            combined.setdefault(variant, set()).update(texts)
    return MappingProxyType(
        {
            variant: tuple(
                sorted(
                    (lookup[text] for text in texts),
                    key=lambda term: (term.class_name, term.text),
                )
            )
            for variant, texts in sorted(combined.items())
        }
    )


def _build_fuzzy_index(
    class_terms: Sequence[Term],
) -> Mapping[str, tuple[str, ...]]:
    index: dict[str, set[str]] = {}
    for term in class_terms:
        if " " in term.text:
            continue
        variants = {term.text, *_deletions(term.text)}
        for variant in variants:
            index.setdefault(variant, set()).add(term.text)
    return MappingProxyType(
        {variant: tuple(sorted(terms)) for variant, terms in sorted(index.items())}
    )


def _deletions(word: str) -> set[str]:
    return {word[:index] + word[index + 1 :] for index in range(len(word))}


def _is_permitted_fuzzy_edit(candidate: str, term: str) -> bool:
    """Return True only for an insertion, deletion, or adjacent transposition."""
    if candidate == term:
        return True
    if abs(len(candidate) - len(term)) > 1:
        return False
    if len(candidate) == len(term):
        return _is_adjacent_transposition(candidate, term)
    return _is_single_insertion_or_deletion(candidate, term)


def _is_adjacent_transposition(left: str, right: str) -> bool:
    index = 0
    limit = len(left) - 1
    while index < limit and left[index] == right[index]:
        index += 1
    return (
        index < limit
        and left[index] == right[index + 1]
        and left[index + 1] == right[index]
        and left[index + 2 :] == right[index + 2 :]
    )


def _is_single_insertion_or_deletion(left: str, right: str) -> bool:
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    return shorter[index:] == longer[index + 1 :]


def _compile_overrides(
    raw: object,
) -> Mapping[str, tuple[re.Pattern[str], ...]]:
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, Mapping):
        msg = "Lexicon key 'overrides' must be an object"
        raise LexiconError(msg)

    compiled: dict[str, tuple[re.Pattern[str], ...]] = {}
    for name, patterns in raw.items():
        if not isinstance(name, str) or not isinstance(patterns, list):
            msg = f"Override {name!r} must be a list of patterns"
            raise LexiconError(msg)
        group: list[re.Pattern[str]] = []
        for pattern in patterns:
            if not isinstance(pattern, str):
                msg = f"Override {name!r} pattern {pattern!r} must be a string"
                raise LexiconError(msg)
            try:
                group.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                msg = f"Override {name!r} pattern {pattern!r} is not a valid " + f"regex: {exc}"
                raise LexiconError(msg) from exc
        compiled[name] = tuple(group)

    return MappingProxyType(dict(sorted(compiled.items())))


def _fold_term(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).lower()
    return _WHITESPACE.sub(" ", folded).strip()
