"""What kind of data a document is: bookings, staff or costs.

Not from the name of the file. Each kind of data is scored from what the document SAYS and HAS: the
words of its title and its sheet names, and - above all - how much of what that kind of import
requires its columns can supply (a bookings file has a reservation code, arrival, departure,
channel; a staff file has hours and a department; a costs file has a supplier, a document number, an
amount). The result is a level, never a percentage on screen:

    HIGH    one kind clearly wins: no question
    MEDIUM  one kind leads: "Questo sembra un file del personale. Corretto?"
    LOW     nothing stands out: "Che tipo di dati contiene questo file?"

The person has already said what they are importing (the card they came from). A verdict that
agrees with it needs no question at any level that points somewhere; a verdict that differs from it,
or that points nowhere, is asked about.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.modules.data_sources.proposal import Proposal
from app.modules.data_sources.semantics import DomainSem, Level
from app.modules.document_understanding.text import tokens
from app.modules.ingestion.models import DataSourceDomain

HIGH_SCORE = 0.62
MEDIUM_SCORE = 0.40
HIGH_MARGIN = 0.20
MEDIUM_MARGIN = 0.08
_FLOOR = 0.25


@dataclass(frozen=True, slots=True)
class DomainScore:
    domain: DataSourceDomain
    score: float
    coverage: float


@dataclass(frozen=True, slots=True)
class DomainVerdict:
    domain: DataSourceDomain | None
    level: Level
    scores: tuple[DomainScore, ...]


def score_domain(
    sem: DomainSem,
    groups: Sequence[tuple[str, ...]],
    proposal: Proposal,
    context_texts: Sequence[str],
    extra_fields: frozenset[str] = frozenset(),
) -> DomainScore:
    """How well a document fits one kind of data. `extra_fields` are fields the document supplies
    without a column of their own (a department that is a line or a sheet, the days of a grid)."""
    assigned = {c.field for c in proposal.columns if c.field is not None} | set(extra_fields)
    sure = {
        c.field
        for c in proposal.columns
        if c.field is not None and c.level in (Level.HIGH, Level.MEDIUM)
    } | set(extra_fields)
    satisfied = sum(1 for group in groups if any(field in sure for field in group))
    coverage = satisfied / len(groups) if groups else 0.0
    breadth = min(1.0, len(assigned) / max(4, len(groups)))
    words: set[str] = set()
    for text in context_texts:
        words |= tokens(text)
    title_hit = 1.0 if words & sem.title_words else 0.0
    score = 0.58 * coverage + 0.24 * breadth + 0.18 * title_hit
    return DomainScore(sem.domain, round(score, 4), round(coverage, 4))


def verdict(scores: Mapping[DataSourceDomain, DomainScore]) -> DomainVerdict:
    ranked = sorted(scores.values(), key=lambda item: -item.score)
    if not ranked or ranked[0].score < _FLOOR:
        return DomainVerdict(None, Level.LOW, tuple(ranked))
    best = ranked[0]
    margin = best.score - (ranked[1].score if len(ranked) > 1 else 0.0)
    if best.score >= HIGH_SCORE and margin >= HIGH_MARGIN:
        return DomainVerdict(best.domain, Level.HIGH, tuple(ranked))
    if best.score >= MEDIUM_SCORE and margin >= MEDIUM_MARGIN:
        return DomainVerdict(best.domain, Level.MEDIUM, tuple(ranked))
    return DomainVerdict(None, Level.LOW, tuple(ranked))


__all__ = ["DomainScore", "DomainVerdict", "score_domain", "verdict"]
