"""What a column MEANS: its name, read by words, checked against its values.

V2 compared the whole header with a list of names, or by how alike the letters were. "Reparto o
mansione" shares too few letters with "reparto" to match, although it plainly says it. Here a header
is read as WORDS: a field has rules like "a word for hours AND a word for planned", so any
header that carries them matches - "Tot. ore previste", "Ore programmate", "Programmed hours".

A match by name is then CHECKED against the values of the column: a header that says "Data" over a
column of names is not a date. How sure NINFA is follows from both:

    HIGH    a known name or the words of a rule, and values that fit, enough of them to prove it
    MEDIUM  a name that is only close, values that only partly fit, or too few values to be sure
    LOW     a guess: the person is asked

Nothing here writes anything or decides a mapping: it proposes, deterministically, and says why.
"""

import difflib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.bookings.mapping import normalize_header
from app.modules.data_sources.relations import Relation
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.stats import MIN_EVIDENCE, ColumnStats
from app.modules.document_understanding.text import fold, stems, tokens
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.suggestions import LOW_THRESHOLD, MEDIUM_THRESHOLD

FitFunction = Callable[[ColumnStats], float]


class Level(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NameMatch(StrEnum):
    EXACT = "EXACT"  # the header is a name NINFA knows for the field
    TOKEN = "TOKEN"  # the header carries the words of a rule
    FUZZY = "FUZZY"  # the header looks like a known name
    VALUES = "VALUES"  # no name at all: only what the values look like


@dataclass(frozen=True, slots=True)
class TokenRule:
    """A header matches when it has a word from EACH group in `all_of` and none from `none_of`."""

    all_of: tuple[frozenset[str], ...]
    none_of: frozenset[str] = frozenset()
    weight: float = 0.9


def rule(*all_of: str, none: str = "", weight: float = 0.9) -> TokenRule:
    """`rule("ore hours", "previste planned")` - each argument is a list of alternative words."""
    return TokenRule(tuple(stems(group) for group in all_of), stems(none), weight)


def rule_score(
    header_words: frozenset[str], rules: Sequence[TokenRule], context: frozenset[str] = frozenset()
) -> float:
    """The best weight among the rules the header satisfies, a little less for each word of the
    header the rule does not explain (a long header with an incidental match is not as good).
    `context` words name the kind of document ("Prenotazione - Registrata il" in a bookings
    file): they are not an incidental extra."""
    return _best_rule(header_words, rules, context)[0]


def rule_index(
    header_words: frozenset[str], rules: Sequence[TokenRule], context: frozenset[str] = frozenset()
) -> int | None:
    """WHICH rule scored best (None when the header satisfies none). Two headers that satisfy the
    same rule say the same thing in different words: "Ore previste", "Ore previste (rev.)"."""
    return _best_rule(header_words, rules, context)[1]


def _best_rule(
    header_words: frozenset[str],
    rules: Sequence[TokenRule],
    context: frozenset[str] = frozenset(),
) -> tuple[float, int | None]:
    best, which = 0.0, None
    for position, candidate in enumerate(rules):
        if candidate.none_of & header_words:
            continue
        if all(group & header_words for group in candidate.all_of):
            explained = frozenset().union(*candidate.all_of)
            extra = len(header_words - explained - context)
            score = candidate.weight - min(0.06, 0.02 * extra)
            if score > best:
                best, which = score, position
    return best, which


@dataclass(frozen=True, slots=True)
class FieldSem:
    key: str
    # Names that mean this field exactly (compared folded, like V2's aliases).
    exact: tuple[str, ...]
    rules: tuple[TokenRule, ...] = ()
    # How well the VALUES of a column fit this field, 0..1 (None: the values say nothing).
    fit: FitFunction | None = None
    # A column may be proposed from its values alone, when it is the only one that fits.
    value_only: bool = False
    # A header with one of these words is never this field, whatever else it says: "Centro di
    # costo" is where a cost is booked, not what it was spent on.
    veto: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class AmbiguousColumn:
    """A column clearly "hours" or "cost" that does not say WHICH one: a question, not a guess."""

    key: str  # "HOURS", "COST", "AMOUNT"
    words: frozenset[str]  # a header with one of these...
    veto: frozenset[str]  # ...and none of these is such a column
    candidates: tuple[str, ...]  # the fields it may be (the person picks one)
    fit: FitFunction | None = None


@dataclass(frozen=True, slots=True)
class DomainSem:
    domain: DataSourceDomain
    fields: Mapping[str, FieldSem]
    order: tuple[str, ...]
    # Stems that mark a title, a sheet name or a header as belonging to this kind of document.
    title_words: frozenset[str]
    # What the personal data of this kind of file is called when it is left out.
    locked: Mapping[PiiKind, str] = field(default_factory=dict)
    ambiguous: tuple[AmbiguousColumn, ...] = ()
    # Rules for columns that must NEVER be offered as a field (an hourly rate): reason by rule.
    never: tuple[tuple[str, TokenRule], ...] = ()
    # Two columns that confirm each other: ((field, folded header), (field, folded header)).
    # "Dal" alone is only a maybe; "Dal" next to "Al", both dates, is an arrival and a departure.
    pairs: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = ()
    # Fields that are MONEY: a choice between two columns for one of them is never made by NINFA
    # and never asked as a yes/no - the person matches the columns by hand.
    financial: frozenset[str] = frozenset()
    # What the VALUES of two columns say about each other (a departure after its arrival): a
    # reading that already stands on a name and on fitting values is promoted by it.
    relations: tuple[Relation, ...] = ()
    # Words that only name the kind of document a header belongs to ("Prenotazione" over a column
    # in a bookings file): they do not count against a rule that explains the rest.
    context: frozenset[str] = frozenset()
    # The most a column can hold PER PERSON per row ("hours worked in a day": 24). When the file
    # lists people (their column is left out of the import) a value above it cannot be what the
    # column says, so the reading is demoted to a question instead of being taken on its name.
    person_limits: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Candidate:
    field: str
    name: NameMatch
    score: float
    # The rule of the field the header satisfies (None: an alias, or a likeness of letters).
    rule: int | None = None


_VOCABULARY: dict[int, dict[str, frozenset[str]]] = {}
_ABBREVIATION = re.compile(r"([^\W\d_]{3,})\.")
MAX_EXPANSIONS = 3


def vocabulary(sem: DomainSem) -> dict[str, frozenset[str]]:
    """Every word (stem) the rules and names of a kind of data use, and the fields it speaks of."""
    known = _VOCABULARY.get(id(sem))
    if known is None:
        fields: dict[str, set[str]] = {}
        for spec in sem.fields.values():
            for candidate in spec.rules:
                for group in candidate.all_of:
                    for word in group:
                        fields.setdefault(word, set()).add(spec.key)
                for word in candidate.none_of:
                    fields.setdefault(word, set())
            for name in spec.exact:
                for word in tokens(name):
                    fields.setdefault(word, set()).add(spec.key)
        known = _VOCABULARY[id(sem)] = {w: frozenset(f) for w, f in fields.items()}
    return known


def expand_abbreviations(sem: DomainSem, header: str) -> frozenset[str]:
    """The words a header abbreviates WITH A POINT: "Descr." is "descrizione", "Aliq." is
    "aliquota". Only a written abbreviation counts (a bare "Pre" is a word of its own), only of a
    word the kind of data knows, and only when the beginning leaves no doubt about WHAT it means:
    every word it could stand for (in either language, at most `MAX_EXPANSIONS`) speaks of the
    same single field. "Imp." could be "imponibile", "imposta" or "importo": three different
    things, so it is not expanded."""
    known = vocabulary(sem)
    out: set[str] = set()
    for match in _ABBREVIATION.finditer(header.casefold()):
        start = fold(match.group(1))
        if not start or start in known or stems(start) <= known.keys():
            continue  # already a word of the vocabulary
        expansions = [word for word in known if word.startswith(start) and len(word) > len(start)]
        fields = {field for word in expansions for field in known[word]}
        if 1 <= len(expansions) <= MAX_EXPANSIONS and len(fields) == 1:
            out.update(expansions)
    return frozenset(out)


def name_candidates(sem: DomainSem, header: str) -> list[Candidate]:
    """Every field the NAME of this header could mean, best first."""
    key = normalize_header(header)
    words = tokens(header) | expand_abbreviations(sem, header)
    found: list[Candidate] = []
    percentage = "perc" in words  # "Commissione %": a rate, whatever the amount is called
    for spec in sem.fields.values():
        if spec.veto & words:
            continue
        # (a header with a standing "%" is not the name of an amount, whatever else it says)
        names_a_rate = not percentage or any("perc" in tokens(name) for name in spec.exact)
        if names_a_rate and key in {normalize_header(name) for name in spec.exact}:
            found.append(
                Candidate(
                    spec.key, NameMatch.EXACT, 1.0, rule_index(words, spec.rules, sem.context)
                )
            )
            continue
        score = rule_score(words, spec.rules, sem.context)
        if score:
            found.append(
                Candidate(
                    spec.key, NameMatch.TOKEN, score, rule_index(words, spec.rules, sem.context)
                )
            )
            continue
        names = [normalize_header(name) for name in spec.exact]
        best = max(
            (difflib.SequenceMatcher(None, key, name).ratio() for name in names), default=0.0
        )
        if best >= LOW_THRESHOLD and key and names_a_rate:
            found.append(Candidate(spec.key, NameMatch.FUZZY, best))
    return sorted(
        found, key=lambda c: (-c.score, sem.order.index(c.field) if c.field in sem.order else 99)
    )


def level_of(name: NameMatch, score: float, fit: float | None, stats: ColumnStats) -> Level:
    """How sure NINFA is that this name AND these values mean the field."""
    values_fit = 0.75 if fit is None else fit  # a field the values say nothing about
    if name in {NameMatch.EXACT, NameMatch.TOKEN}:
        if name == NameMatch.TOKEN and score < 0.8:
            return Level.MEDIUM if values_fit >= 0.5 else Level.LOW  # a loose rule: to be checked
        if fit is not None and fit >= 0.85 and stats.enough():
            return Level.HIGH
        if fit is None and stats.enough():
            return Level.HIGH if name == NameMatch.EXACT or score >= 0.88 else Level.MEDIUM
        if values_fit >= 0.5:
            return Level.MEDIUM
        return Level.LOW
    if name == NameMatch.FUZZY:
        if score >= MEDIUM_THRESHOLD and values_fit >= 0.85 and stats.enough():
            return Level.MEDIUM
        return Level.LOW
    # values alone
    return Level.MEDIUM if values_fit >= 0.9 and stats.enough() else Level.LOW


# --- how values fit -------------------------------------------------------------------------------


def fit_date(stats: ColumnStats) -> float:
    return stats.date_fraction


def fit_hours(stats: ColumnStats) -> float:
    if not stats.n or stats.maximum is None or stats.minimum is None:
        return 0.0
    if stats.minimum < 0 or stats.maximum > 168:
        return 0.2 * stats.numeric_fraction
    return stats.numeric_fraction


def fit_money(stats: ColumnStats, *, allow_negative: bool = False) -> float:
    if not stats.n or stats.hours_unit:  # "120 h" is hours, not euros
        return 0.0
    if stats.negatives and not allow_negative:
        return 0.3 * stats.numeric_fraction
    return stats.numeric_fraction


def fit_small_integer(maximum: int) -> FitFunction:
    def fit(stats: ColumnStats) -> float:
        if not stats.n or stats.maximum is None or stats.minimum is None or stats.hours_unit:
            return 0.0
        if stats.minimum < 0 or stats.maximum > maximum or stats.integral < stats.numeric:
            return 0.0
        return stats.numeric_fraction

    return fit


def fit_percentage(stats: ColumnStats) -> float:
    if not stats.n or stats.maximum is None or stats.minimum is None or stats.hours_unit:
        return 0.0
    return stats.numeric_fraction if stats.minimum >= 0 and stats.maximum <= 100 else 0.0


def fit_label(stats: ColumnStats) -> float:
    """Text that repeats: a department, a channel, a status, a rate plan."""
    if not stats.n:
        return 0.0
    if stats.text_fraction < 0.8:
        return 0.0
    return 1.0 if (stats.distinct_ratio <= 0.7 or stats.distinct <= 25) else 0.6


def fit_text(stats: ColumnStats) -> float:
    return stats.text_fraction if stats.n else 0.0


def fit_identifier(stats: ColumnStats) -> float:
    """Mostly different from row to row: a booking code, a document number."""
    if not stats.n:
        return 0.0
    if stats.date_fraction > 0.5:
        return 0.0
    return min(1.0, stats.distinct_ratio + 0.05)


def fit_unique_identifier(stats: ColumnStats) -> float:
    """An identifier that must be DIFFERENT on every row: a booking code. A reference that repeats
    (a group, a company, a convention) names a set of bookings, not one booking, so it is not the
    code however it is called. (An invoice number, by contrast, legitimately repeats over the
    lines of one invoice: that is `fit_identifier`.)"""
    base = fit_identifier(stats)
    if not stats.n or stats.distinct_ratio >= 0.9:
        return base
    return min(base, 0.25)  # (still a candidate - to be asked about - but never a sure one)


def fit_vocabulary(check: Callable[[str], bool]) -> FitFunction:
    """Text whose distinct values are, for the most part, words the domain knows."""

    def fit(stats: ColumnStats) -> float:
        base = fit_label(stats)
        if not base or not stats.texts:
            return base
        known = sum(1 for text in stats.texts if check(text)) / len(stats.texts)
        return 1.0 if known >= 0.6 else 0.8 * base

    return fit


_CURRENCIES = frozenset({"eur", "usd", "gbp", "chf", "euro", "€", "$", "£"})


def fit_currency(stats: ColumnStats) -> float:
    if not stats.n or not stats.texts:
        return 0.0
    known = sum(1 for text in stats.texts if text.strip().lower() in _CURRENCIES)
    return known / len(stats.texts)


__all__ = [
    "AmbiguousColumn",
    "Candidate",
    "DomainSem",
    "FieldSem",
    "FitFunction",
    "Level",
    "NameMatch",
    "TokenRule",
    "fit_currency",
    "fit_date",
    "fit_hours",
    "fit_identifier",
    "fit_label",
    "fit_money",
    "fit_percentage",
    "fit_small_integer",
    "fit_text",
    "fit_unique_identifier",
    "fit_vocabulary",
    "level_of",
    "name_candidates",
    "rule",
    "rule_index",
    "rule_score",
    "MIN_EVIDENCE",
]
