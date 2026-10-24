"""From the columns of a table to a PROPOSAL: what each column means, how sure, and why.

    1. columns that must not be read at all are set apart first (personal data, an hourly rate);
    2. every other column is compared with every field - by its name, then by its values;
    3. the best matches are taken, each field once and each column once;
    4. a column that is clearly "hours" or "an amount" but does not say which is NOT guessed: it is
       reported as ambiguous, so the person can be asked that single thing.

The result is a proposal, never a mapping: only a confirmed decision, checked by the import
service's own rules, becomes one.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.semantics import (
    Candidate,
    DomainSem,
    Level,
    NameMatch,
    level_of,
    name_candidates,
    rule_score,
)
from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.stats import MIN_EVIDENCE, ColumnStats, column_stats
from app.modules.document_understanding.text import fold, tokens

_LEVEL_RANK = {Level.HIGH: 3, Level.MEDIUM: 2, Level.LOW: 1}
_VALUE_ONLY_FIT = 0.9


@dataclass(frozen=True, slots=True)
class ColumnProposal:
    position: int
    header: str
    stats: ColumnStats
    field: str | None = None
    level: Level | None = None
    name: NameMatch | None = None
    fit: float | None = None
    # Why the column is left out altogether ("PERSON", "CONTACT", "IDENTITY", "HOURLY_RATE").
    locked: str | None = None
    pii: PiiKind | None = None
    # A column that is "hours" or "an amount" without saying which: the group and what it may be.
    ambiguous_group: str | None = None
    ambiguous_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Proposal:
    columns: tuple[ColumnProposal, ...]

    def field_of(self, header: str) -> str | None:
        return next((c.field for c in self.columns if c.header == header), None)

    def assigned(self) -> dict[str, ColumnProposal]:
        return {c.field: c for c in self.columns if c.field is not None}


def propose(
    sem: DomainSem,
    samples: Sequence[ColumnSample],
    *,
    excluded_reason: Callable[[str], str | None] = lambda _header: None,
) -> Proposal:
    stats = [column_stats(sample.values) for sample in samples]

    # 1. what is never read
    locked: dict[int, tuple[str, PiiKind | None]] = {}
    for index, sample in enumerate(samples):
        reason = excluded_reason(sample.header)
        finding = detect_pii(sample.header, stats[index])
        pii = finding.kind if finding else None
        if reason is None and finding is not None:
            reason = sem.locked.get(finding.kind)
        if reason is None:
            words = tokens(sample.header)
            for code, never in sem.never:
                if rule_score(words, (never,)):
                    reason = code
                    break
        if reason is not None:
            locked[index] = (reason, pii)

    # 2. every column against every field
    entries: list[tuple[int, float, int, int, str, NameMatch, float | None, Level]] = []
    have_name: set[str] = set()
    for index, sample in enumerate(samples):
        if index in locked:
            continue
        says_which_is_missing = _ambiguous_words(sem, sample.header)
        for candidate in name_candidates(sem, sample.header):
            if candidate.name == NameMatch.FUZZY and says_which_is_missing:
                continue  # "Costo totale" looks like a cost, but not WHICH one: that is a question
            spec = sem.fields[candidate.field]
            fit = spec.fit(stats[index]) if spec.fit is not None else None
            if fit is not None and stats[index].n >= MIN_EVIDENCE and fit < 0.2:
                continue  # the values contradict the name
            level = level_of(candidate.name, candidate.score, fit, stats[index])
            order = sem.order.index(candidate.field) if candidate.field in sem.order else 99
            entries.append(
                (
                    _LEVEL_RANK[level],
                    candidate.score,
                    -order,
                    -index,
                    candidate.field,
                    candidate.name,
                    fit,
                    level,
                )
            )
            have_name.add(candidate.field)

    # 3. a field no name points at may be proposed from the values of the one column that fits
    for key, spec in sem.fields.items():
        if not spec.value_only or key in have_name or spec.fit is None:
            continue
        fitting = [
            index
            for index in range(len(samples))
            if index not in locked
            and stats[index].enough()
            and spec.fit(stats[index]) >= _VALUE_ONLY_FIT
            and not any(e[3] == -index for e in entries)
        ]
        if len(fitting) == 1:
            index = fitting[0]
            level = level_of(NameMatch.VALUES, 0.5, spec.fit(stats[index]), stats[index])
            order = sem.order.index(key) if key in sem.order else 99
            entries.append(
                (
                    _LEVEL_RANK[level],
                    0.5,
                    -order,
                    -index,
                    key,
                    NameMatch.VALUES,
                    spec.fit(stats[index]),
                    level,
                )
            )

    # 4. take the best, each field once, each column once
    taken_fields: set[str] = set()
    taken_columns: set[int] = set()
    chosen: dict[int, tuple[str, NameMatch, float | None, Level]] = {}
    for rank, _score, _order, neg_index, key, name, fit, level in sorted(entries, reverse=True):
        index = -neg_index
        if key in taken_fields or index in taken_columns:
            continue
        taken_fields.add(key)
        taken_columns.add(index)
        chosen[index] = (key, name, fit, level)
        del rank

    # 5. columns that confirm each other
    for (field_a, header_a), (field_b, header_b) in sem.pairs:
        a = next((i for i, c in chosen.items() if c[0] == field_a), None)
        b = next((i for i, c in chosen.items() if c[0] == field_b), None)
        if (
            a is not None
            and b is not None
            and fold(samples[a].header) == header_a
            and fold(samples[b].header) == header_b
            and stats[a].enough()
            and stats[b].enough()
            and (chosen[a][2] or 0) >= 0.9
            and (chosen[b][2] or 0) >= 0.9
        ):
            for index in (a, b):
                key, name, fit, _ = chosen[index]
                chosen[index] = (key, name, fit, Level.HIGH)

    # 6. "hours" / "an amount" that does not say which
    out: list[ColumnProposal] = []
    for index, sample in enumerate(samples):
        if index in locked:
            reason, pii = locked[index]
            out.append(ColumnProposal(index, sample.header, stats[index], locked=reason, pii=pii))
            continue
        if index in chosen:
            key, name, fit, level = chosen[index]
            out.append(ColumnProposal(index, sample.header, stats[index], key, level, name, fit))
            continue
        group = _ambiguous(sem, sample.header, stats[index], taken_fields)
        if group is not None:
            out.append(
                ColumnProposal(
                    index,
                    sample.header,
                    stats[index],
                    ambiguous_group=group[0],
                    ambiguous_fields=group[1],
                )
            )
            continue
        out.append(ColumnProposal(index, sample.header, stats[index]))
    return Proposal(tuple(out))


def _ambiguous_words(sem: DomainSem, header: str) -> bool:
    words = tokens(header)
    return any(group.words & words and not group.veto & words for group in sem.ambiguous)


def _ambiguous(
    sem: DomainSem, header: str, stats: ColumnStats, taken: set[str]
) -> tuple[str, tuple[str, ...]] | None:
    words = tokens(header)
    for group in sem.ambiguous:
        if not (group.words & words) or group.veto & words:
            continue
        if group.fit is not None and (not stats.enough() or group.fit(stats) < 0.9):
            continue
        free = tuple(field for field in group.candidates if field not in taken)
        if free:
            return group.key, free
    return None


__all__ = ["Candidate", "ColumnProposal", "Level", "Proposal", "propose"]
