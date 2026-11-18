"""Reading a header the way a person does, then matching it with the hospitality vocabulary.

Two steps, both deterministic:

1. NORMALISE. `BookingStatus`, `booking_status`, `booking-status`, `Booking Status (PMS)` and
   `bookingstatus` are one header. camelCase is split, a qualifier in brackets ("(EUR)") is set
   aside, punctuation and accents are folded, "n.", "nr", "no", "#" are the word "number", a header
   written without spaces is cut into the words of the vocabulary. The RAW header is never lost: it
   is what the importer matches columns by and what the audit shows.

2. MATCH. A normalised header is compared with the phrases of each field:

       exact       the same words                         1.00
       reordered   the same words in another order        0.97
       in context  the same words plus a word that only   0.95
                   names the kind of file ("reservation arrival")
       typo        the same words, where a word is a      0.80 - 0.99 (the mean likeness)
                   near spelling of the phrase's ("arival", "prenotazine")

   RapidFuzz measures how alike two WORDS are, never two whole headers: a header that differs from
   a phrase by a different word is a different header, however many letters they share ("check
   in" and "check out" are 80% alike as strings). A header equal to a phrase that means ANOTHER
   thing ("ADR", "Room nights") is blocked for the field it resembles.

The phrases are the vocabulary's plus the names the kind of data already knows for each field (the
importer's own aliases), so nothing V3 read by a likeness of letters is lost.

The result is evidence, never a mapping: it is one component of the candidate score.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from itertools import product

from rapidfuzz import fuzz, process

from app.modules.data_sources.algorithmic import vocabulary
from app.modules.document_understanding.text import STOP_WORDS, fold
from app.modules.ingestion.models import DataSourceDomain

# word-to-word likeness (0-100) a spelling mistake keeps; shorter words must match exactly
TYPO_CUTOFF = 85
MIN_TYPO_LENGTH = 4
MAX_TYPO_OPTIONS = 3
MAX_COMBINATIONS = 128
MIN_GLUED_LENGTH = 6
MAX_GLUED_PIECES = 4
_SHORT_PIECES = frozenset({"in", "id", "no", "di", "da", "of"})

_NUMBER_WORDS = frozenset({"n", "nr", "nro", "num", "numero", "no", "nbr", "number", "nb"})
_TOTAL_WORDS = frozenset({"tot", "totale", "totali", "total", "totals"})
_QUALIFIER = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TRAILING_MARK = re.compile(r"[\s*:#?!]+$")

Extras = tuple[tuple[str, tuple[str, ...]], ...]


class Kind(StrEnum):
    EXACT = "EXACT"
    REORDERED = "REORDERED"
    IN_CONTEXT = "IN_CONTEXT"
    TYPO = "TYPO"


_SCORES = {Kind.EXACT: 1.0, Kind.REORDERED: 0.97, Kind.IN_CONTEXT: 0.95}


@dataclass(frozen=True, slots=True)
class Header:
    """A header read for matching. `raw` is exactly what the file says."""

    raw: str
    text: str
    words: tuple[str, ...]
    qualifier: str = ""

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(sorted(self.words))


@dataclass(frozen=True, slots=True)
class HeaderMatch:
    field: str
    kind: Kind
    score: float
    phrase: str  # the vocabulary phrase it matched: never a value of the file


@dataclass(frozen=True, slots=True)
class HeaderReading:
    header: Header
    matches: dict[str, HeaderMatch]
    # fields this header must NOT be, because it is a phrase that means something else
    blocked: frozenset[str]


# --- normalising ----------------------------------------------------------------------------------


def split_camel(text: str) -> str:
    """`BookingStatus` -> `Booking Status`, `PMSId` -> `PMS Id` (digits are left where they are)."""
    return _CAMEL.sub(" ", text)


def _canonical_word(word: str) -> str:
    if word in _NUMBER_WORDS:
        return "number"
    if word in _TOTAL_WORDS:
        return "total"
    return word


def _words_of(text: str) -> list[str]:
    spaced = text.replace("%", " perc ").replace("#", " number ")
    words = fold(spaced).split()
    merged: list[str] = []
    for word in words:
        if word == "ta" and merged and merged[-1] == "q":
            merged[-1] = "qta"  # "Q.tà"
        elif word == "o" and merged and merged[-1] == "u":
            merged[-1] = "uo"  # "U.O."
        elif word == "u" and merged and merged[-1] == "p":
            merged[-1] = "pu"  # "P.U."
        else:
            merged.append(word)
    return [_canonical_word(word) for word in merged if word not in STOP_WORDS]


def _segment(word: str, known: frozenset[str]) -> list[str] | None:
    """A word written without spaces, cut into the fewest words of the vocabulary that cover it
    entirely ("checkindate" -> check, in, date). None when it cannot be covered."""
    size = len(word)
    best: list[list[str] | None] = [None] * (size + 1)
    best[0] = []
    for end in range(1, size + 1):
        for start in range(max(0, end - 14), end):
            piece = word[start:end]
            previous = best[start]
            if previous is None or len(previous) >= MAX_GLUED_PIECES:
                continue
            if piece not in known or (len(piece) < 3 and piece not in _SHORT_PIECES):
                continue
            candidate = [*previous, piece]
            if best[end] is None or len(candidate) < len(best[end] or []):
                best[end] = candidate
    found = best[size]
    return found if found and len(found) > 1 else None


def normalize(raw: str) -> Header:
    """The header as a list of comparable words. Never raises, never loses `raw`."""
    qualifier = " ".join(match.strip("()[]{} ") for match in _QUALIFIER.findall(raw))
    core = _QUALIFIER.sub(" ", raw)
    if not any(ch.isalpha() for ch in core):  # "(EUR)" alone is the header, not a qualifier
        core, qualifier = raw, ""
    core = _TRAILING_MARK.sub("", split_camel(core.strip()))
    known = vocabulary_words()
    spellings = known | segmentation_fillers()
    words: list[str] = []
    for word in _words_of(core):
        if word not in known and len(word) >= MIN_GLUED_LENGTH and word.isalpha():
            pieces = _segment(word, spellings)
            if pieces is not None:
                # the pieces get the treatment a spaced header gets: "di" is not a word of a
                # header, "numero" is the word "number"
                words.extend(_canonical_word(piece) for piece in pieces if piece not in STOP_WORDS)
                continue
        words.append(word)
    return Header(raw, " ".join(words), tuple(words), qualifier)


# --- the vocabulary of one kind of data, indexed -------------------------------------------------


def _phrase_words(phrase: str) -> tuple[str, ...]:
    return tuple(_words_of(split_camel(phrase)))


@cache
def segmentation_fillers() -> frozenset[str]:
    """The spellings a glued header may be made of that the vocabulary folds away: "numero",
    "totale" (the words "number" and "total") and the little words that join ("di", "del", "of")."""
    return frozenset(_NUMBER_WORDS | _TOTAL_WORDS | {w for w in STOP_WORDS if len(w) >= 2})


@cache
def vocabulary_words() -> frozenset[str]:
    """Every word the phrases use, folded as the matcher folds a header."""
    words: set[str] = set()
    for fields in (*vocabulary.ALIASES.values(), *vocabulary.NOT_THE_FIELD.values()):
        for phrases in fields.values():
            for phrase in phrases:
                words.update(_phrase_words(phrase))
    for contexts in vocabulary.CONTEXT_WORDS.values():
        words.update(contexts)
    return frozenset(words)


class DomainVocabulary:
    """The phrases of one kind of data, ready to match a header against."""

    def __init__(self, domain: DataSourceDomain, extras: Extras = ()) -> None:
        self.domain = domain
        self.ordered: dict[tuple[str, ...], list[tuple[str, str]]] = {}
        self.unordered: dict[tuple[str, ...], list[tuple[str, str]]] = {}
        self.not_fields: dict[tuple[str, ...], set[str]] = {}
        words: set[str] = set(vocabulary_words())
        sources = [
            (field, phrase)
            for field, phrases in vocabulary.ALIASES.get(domain, {}).items()
            for phrase in phrases
        ]
        sources.extend((field, phrase) for field, phrases in extras for phrase in phrases)
        for field, phrase in sources:
            seq = _phrase_words(phrase)
            if not seq:
                continue
            words.update(seq)
            self.ordered.setdefault(seq, []).append((field, phrase))
            self.unordered.setdefault(tuple(sorted(seq)), []).append((field, phrase))
        for field, phrases in vocabulary.NOT_THE_FIELD.get(domain, {}).items():
            for phrase in phrases:
                seq = _phrase_words(phrase)
                if seq:
                    self.not_fields.setdefault(tuple(sorted(seq)), set()).add(field)
        self.word_set = frozenset(words)
        self.words = tuple(sorted(words))
        self.context = vocabulary.CONTEXT_WORDS.get(domain, frozenset())

    # --- matching ---

    def _typo_options(self, word: str) -> list[tuple[str, float]]:
        """The spellings a word could be a typo of: itself, then near words of the vocabulary."""
        if word in self.word_set:
            return [(word, 1.0)]
        if len(word) < MIN_TYPO_LENGTH:
            return []
        near = process.extract(
            word,
            self.words,
            scorer=fuzz.ratio,
            score_cutoff=TYPO_CUTOFF,
            limit=MAX_TYPO_OPTIONS,
        )
        return [
            (found, ratio / 100.0)
            for found, ratio, _position in near
            if len(found) >= MIN_TYPO_LENGTH and abs(len(found) - len(word)) <= 2
        ]

    def _variants(self, words: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], float]]:
        """Every reading of the words as a spelling of known words, with how alike they are."""
        options = [self._typo_options(word) for word in words]
        if not all(options):
            return
        total = 1
        for choices in options:
            total *= len(choices)
        if total > MAX_COMBINATIONS:
            return
        for combination in product(*options):
            yield (
                tuple(word for word, _ in combination),
                sum(likeness for _, likeness in combination) / len(combination),
            )

    def read(self, raw: str) -> HeaderReading:
        """What the phrases say a header of this kind of data means. Never raises."""
        header = normalize(raw)
        matches: dict[str, HeaderMatch] = {}
        blocked: set[str] = set()
        if not header.words:
            return HeaderReading(header, matches, frozenset())

        stripped = tuple(word for word in header.words if word not in self.context)
        attempts: list[tuple[tuple[str, ...], bool]] = [(header.words, False)]
        if stripped and stripped != header.words:
            attempts.append((stripped, True))

        for words, dropped_context in attempts:
            key = tuple(sorted(words))
            for field, phrase in self.ordered.get(words, ()):
                kind = Kind.IN_CONTEXT if dropped_context else Kind.EXACT
                matches[field] = _better(
                    matches.get(field), HeaderMatch(field, kind, _SCORES[kind], phrase)
                )
            for field, phrase in self.unordered.get(key, ()):
                kind = Kind.IN_CONTEXT if dropped_context else Kind.REORDERED
                matches[field] = _better(
                    matches.get(field), HeaderMatch(field, kind, _SCORES[kind], phrase)
                )
            blocked.update(self.not_fields.get(key, ()))
            for variant, likeness in self._variants(words):
                if variant == words:
                    continue
                if _opposite(frozenset(words), frozenset(variant)):
                    continue
                variant_key = tuple(sorted(variant))
                penalty = 0.02 if dropped_context else 0.0
                for field, phrase in self.unordered.get(variant_key, ()):
                    matches[field] = _better(
                        matches.get(field),
                        HeaderMatch(field, Kind.TYPO, round(likeness - penalty, 4), phrase),
                    )
                blocked.update(self.not_fields.get(variant_key, ()))

        for name in blocked:
            matches.pop(name, None)
        return HeaderReading(header, matches, frozenset(blocked))


def _better(old: HeaderMatch | None, new: HeaderMatch) -> HeaderMatch:
    return new if old is None or new.score > old.score else old


def _opposite(header_words: frozenset[str], phrase_words: frozenset[str]) -> bool:
    """Do the two differ by a pair of opposites and nothing else? ("check in" / "check out")"""
    only_header, only_phrase = header_words - phrase_words, phrase_words - header_words
    if not only_header or not only_phrase:
        return False
    return any(
        (a in only_header and b in only_phrase) or (b in only_header and a in only_phrase)
        for a, b in vocabulary.OPPOSITES
    )


@cache
def _domain_vocabulary(domain: DataSourceDomain, extras: Extras) -> DomainVocabulary:
    return DomainVocabulary(domain, extras)


def domain_vocabulary(
    domain: DataSourceDomain, names: Mapping[str, tuple[str, ...]] | None = None
) -> DomainVocabulary:
    """The (cached) vocabulary of a kind of data, with the names the kind of data already has for
    each field (`FieldSem.exact`) added to the phrases."""
    extras: Extras = tuple(
        sorted((field, tuple(phrases)) for field, phrases in (names or {}).items())
    )
    return _domain_vocabulary(domain, extras)


def read_header(
    domain: DataSourceDomain, raw: str, names: Mapping[str, tuple[str, ...]] | None = None
) -> HeaderReading:
    return domain_vocabulary(domain, names).read(raw)


__all__ = [
    "DomainVocabulary",
    "Header",
    "HeaderMatch",
    "HeaderReading",
    "Kind",
    "domain_vocabulary",
    "normalize",
    "read_header",
    "split_camel",
    "vocabulary_words",
]
