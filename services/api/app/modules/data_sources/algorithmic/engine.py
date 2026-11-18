"""Smart Import V4 - the algorithmic selection engine.

It replaces ONE step of the understanding (which column is which field) and nothing around it:

    V3  greedy        every column against every field by its name, then by its values; take the
                      best-looking pair first
    V4  algorithmic   1 header evidence    V3's word rules and names, PLUS the hospitality
                                           vocabulary read with RapidFuzz (typos, order, camelCase,
                                           glued words), minus phrases that mean another thing
                      2 value evidence     what the values fit, what they prove with no helpful name
                                           (a status, a channel, a booking code...), what
                                           they RULE OUT
                      3 relations          booked <= arrival < departure, net + VAT = total
                      4 candidate score    one total per (column, field), with its parts
                      5 selection          V3's greedy pick over those scores (the DEFAULT) - or,
                                           optionally, the best reading of the whole file with scipy
                                           (`ASSIGN`), where a pair another reading matches within
                                           `margin` is not firm (`MARGIN`: a HIGH becomes MEDIUM)
                      6 validation         NINFA's domain rules applied to what was chosen

The levels (HIGH / MEDIUM / LOW) still come from V3's `level_of`, so a reading is exactly as sure as
it would have been in V3 for the same evidence; V4 adds readings and takes certainty AWAY, it never
adds certainty a name and values did not already earn. What follows the selection (look-alike
columns, partner columns, values no person could have, "hours" that do not say which, then every
question, blocker and validator) is the same code for both engines.

The configuration exists for ONE reason: to measure what each part is worth (`HEADER_ONLY`,
`DEFAULT`, `ASSIGN`, `MARGIN`) and to switch back (`SMART_IMPORT_UNDERSTANDING_ENGINE=v3`). The
global assignment is not the default because, measured over 1,026 documents, it changed one reading
and for the worse (see the benchmark report).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.modules.data_sources.algorithmic.assignment import assign
from app.modules.data_sources.algorithmic.header import HeaderReading, Kind, read_header
from app.modules.data_sources.algorithmic.profile import ColumnProfile, profile_column
from app.modules.data_sources.algorithmic.relational import Relational, relations_of
from app.modules.data_sources.algorithmic.scoring import CandidateScore, combine
from app.modules.data_sources.algorithmic.validate import Finding, validate_reading
from app.modules.data_sources.algorithmic.values import PROVABLE, proof_of, read_values, semantic_of
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.proposal import (
    Entry,
    Selection,
    ambiguous_words,
    greedy_pick,
)
from app.modules.data_sources.semantics import (
    Candidate,
    DomainSem,
    Level,
    NameMatch,
    level_of,
    name_candidates,
    rule_index,
)
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.stats import MIN_EVIDENCE, ColumnStats
from app.modules.document_understanding.text import fold, tokens

_LEVEL_RANK = {Level.HIGH: 3, Level.MEDIUM: 2, Level.LOW: 1}
_VALUE_ONLY_FIT = 0.9  # as V3: a reading from the values alone needs values that fit this well
_VALUE_ONLY_SCORE = 0.5
_NAME_OF = {
    Kind.EXACT: NameMatch.EXACT,
    Kind.REORDERED: NameMatch.TOKEN,
    Kind.IN_CONTEXT: NameMatch.TOKEN,
    Kind.TYPO: NameMatch.FUZZY,
}


@dataclass(frozen=True, slots=True)
class AlgorithmicConfig:
    name: str = "v4"
    header: bool = True  # the vocabulary + RapidFuzz, in place of V3's likeness of letters
    values: bool = True  # value proof, negative evidence, relations
    assignment: bool = True  # scipy global assignment (False: V3's greedy over the same readings)
    # a reading another one matches within this much is not firm (0: never judged by it)
    margin: float = 0.10
    # what a close second reading does to a reading that rests on a NAME: demotes a HIGH to a
    # question (True) or leaves V3's own tie-break alone (False). A reading from the values alone is
    # always dropped when another one is as likely: V3 has no tie-break there.
    demote_names: bool = False
    # a column may be named by its values alone only in a file that already looks like this kind of
    # data: this many different fields named by their headers (or a relation between the dates)
    support: int = 3


# `v4-header`   the vocabulary and RapidFuzz only
# `v4`          + what the values prove and rule out, the relations, the domain validation: what
#               `SMART_IMPORT_UNDERSTANDING_ENGINE=v4` runs. V3's greedy pick over V4's evidence.
# `v4-assign`   + SciPy's global assignment. MEASURED: over 1,026 documents it changed ONE reading,
# for
#               the worse (benchmark report), so it is not the default; the code stays, tested, for
#               the day a file shows what greedy cannot. Needs SciPy (a development dependency).
# `v4-margin`   `v4-assign` that also turns a NAME-based HIGH into a question when a close second
# reading exists. Measured: it costs READY and buys no safety V4 does not already have.
HEADER_ONLY = AlgorithmicConfig("v4-header", values=False, assignment=False)
DEFAULT = AlgorithmicConfig("v4", assignment=False)
ASSIGN = AlgorithmicConfig("v4-assign")
MARGIN = AlgorithmicConfig("v4-margin", demote_names=True)
CONFIGS = {config.name: config for config in (HEADER_ONLY, DEFAULT, ASSIGN, MARGIN)}

# What a level is worth in the assignment. V3 took the pairs a name and values CONFIRM before the
# ones they only partly confirm; a total that ignored the level would let a loose name over loose
# values outbid a firm one ("Job Title" over "Operating Unit").
LEVEL_BONUS = {Level.HIGH: 0.40, Level.MEDIUM: 0.20, Level.LOW: 0.0}


@dataclass(slots=True)
class _Reading:
    """One (column, field) pair on its way to a score."""

    candidate: Candidate
    kind: str
    phrase: str | None


@dataclass(slots=True)
class Trace:
    """Everything the engine weighed, for a test, a report or a person debugging a reading."""

    scores: list[CandidateScore] = field(default_factory=list)
    selected: dict[int, tuple[str, float, Level]] = field(
        default_factory=dict
    )  # col -> field, margin
    dropped: dict[int, str] = field(default_factory=dict)
    relations: dict[tuple[int, str], str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


class AlgorithmicEngine:
    def __init__(
        self,
        config: AlgorithmicConfig = DEFAULT,
        *,
        on_trace: Callable[[Trace], None] | None = None,
    ) -> None:
        self.config = config
        self._on_trace = on_trace

    # --- the selection ----------------------------------------------------------------------------

    def select(
        self,
        sem: DomainSem,
        samples: Sequence[ColumnSample],
        stats: Sequence[ColumnStats],
        locked: dict[int, tuple[str, PiiKind | None]],
        personal: dict[int, PiiKind],
    ) -> Selection:
        config = self.config
        domain = sem.domain
        columns = [i for i in range(len(samples)) if i not in locked]
        trace = Trace()

        profiles: list[ColumnProfile] = []
        relational = Relational()
        if config.values:
            profiles = [
                profile_column(samples[i], stats[i], pii=personal.get(i), locked=i in locked)
                for i in range(len(samples))
            ]
            relational = relations_of(domain, samples, profiles)
            trace.relations = dict(relational.reasons)

        names = {key: spec.exact for key, spec in sem.fields.items()}
        scored: dict[tuple[int, str], tuple[Candidate, Level]] = {}
        fits: dict[tuple[int, str], float | None] = {}
        totals: dict[tuple[int, str], float] = {}
        table: dict[tuple[int, str], CandidateScore] = {}
        named_columns: set[int] = set()
        have_name: set[str] = set()

        # 1-4. header evidence, value evidence, relations -> one score per (column, field)
        for index in columns:
            readings = self._header_readings(sem, samples[index].header, names)
            blocked = readings.blocked if readings is not None else frozenset()
            candidates = self._candidates(sem, samples[index].header, readings)
            says_which_is_missing = ambiguous_words(sem, samples[index].header)
            for found in candidates.values():
                name = found.candidate.field
                spec = sem.fields[name]
                if name in blocked:
                    self._record(
                        table, index, found, None, 0.0, 0.0, "a phrase that means something else"
                    )
                    continue
                if found.candidate.name == NameMatch.FUZZY and says_which_is_missing:
                    continue  # "Costo totale" looks like a cost, but not WHICH one: a question
                if readings is not None and spec.veto & tokens(readings.header.text):
                    continue
                fit = spec.fit(stats[index]) if spec.fit is not None else None
                veto: str | None = None
                notes: tuple[str, ...] = ()
                if config.values:
                    evidence = read_values(domain, name, fit, profiles[index])
                    veto, notes = evidence.veto, evidence.reasons
                if (
                    veto is None
                    and fit is not None
                    and stats[index].n >= MIN_EVIDENCE
                    and fit < 0.2
                ):
                    veto = "the values contradict the name"
                bonus = relational.bonus.get((index, name), 0.0)
                total = combine(found.candidate.score, fit, 0.0, bonus, veto)
                self._record(table, index, found, fit, 0.0, bonus, veto, total, notes)
                if veto is not None:
                    continue
                level = level_of(found.candidate.name, found.candidate.score, fit, stats[index])
                scored[(index, name)] = (found.candidate, level)
                fits[(index, name)] = fit
                totals[(index, name)] = total + (LEVEL_BONUS[level] if config.assignment else 0.0)
                named_columns.add(index)
                have_name.add(name)

        # a column with NO name that says anything may still be named by what its values prove
        if config.values:
            self._values_alone(
                sem,
                samples,
                stats,
                profiles,
                relational,
                columns,
                named_columns,
                have_name,
                scored,
                fits,
                totals,
                table,
                trace,
            )

        # 5. the best reading of the whole file
        order = list(sem.order) + [key for key in sem.fields if key not in sem.order]
        chosen: dict[int, tuple[str, NameMatch, float | None, Level]] = {}
        notes_out: dict[int, list[str]] = {}
        if config.assignment:
            result = assign(totals, columns, order)
            for column, name in result.pairs.items():
                candidate, level = scored[(column, name)]
                margin = result.margins[column]
                about = table[(column, name)]
                why = list(about.notes)
                if about.relational:
                    why.append(f"relation: {trace.relations.get((column, name), '')}")
                if about.header_kind not in ("VALUES", "RULE"):
                    why.append(f"header {about.header_kind.lower()} '{about.phrase}'")
                if config.margin and margin < config.margin:
                    if candidate.name == NameMatch.VALUES:
                        trace.dropped[column] = (
                            f"{name}: another reading is as likely (margin {margin:.2f})"
                        )
                        continue
                    if config.demote_names and level == Level.HIGH:
                        level = Level.MEDIUM
                        why.append(
                            f"not firm: another reading is nearly as likely (margin {margin:.2f})"
                        )
                chosen[column] = (name, candidate.name, fits.get((column, name)), level)
                notes_out[column] = why
                trace.selected[column] = (name, margin, level)
            taken = {name for name, *_rest in chosen.values()}
        else:
            entries: list[Entry] = []
            for (column, name), (candidate, level) in scored.items():
                position = order.index(name) if name in order else 99
                entries.append(
                    (
                        _LEVEL_RANK[level],
                        candidate.score,
                        -position,
                        -column,
                        name,
                        candidate.name,
                        fits.get((column, name)),
                        level,
                    )
                )
            chosen, taken = greedy_pick(entries)
            for column, (name, _name, _fit, level) in chosen.items():
                trace.selected[column] = (name, float("nan"), level)
                about = table[(column, name)]
                notes_out[column] = list(about.notes)

        # NINFA's domain rules, applied to what was chosen: certainty can only go down
        if config.values:
            trace.findings = validate_reading(
                domain, {column: value[0] for column, value in chosen.items()}, samples
            )
            for finding in trace.findings:
                name, kind, fit, level = chosen[finding.column]
                if _LEVEL_RANK[finding.level] < _LEVEL_RANK[level]:
                    chosen[finding.column] = (name, kind, fit, finding.level)
                    trace.selected[finding.column] = (
                        name,
                        trace.selected.get(finding.column, (name, float("nan"), level))[1],
                        finding.level,
                    )
                notes_out.setdefault(finding.column, []).append(finding.reason)

        trace.scores = list(table.values())
        if self._on_trace is not None:
            self._on_trace(trace)
        return Selection(scored, fits, chosen, taken, notes_out)

    # --- header evidence --------------------------------------------------------------------------

    def _header_readings(
        self, sem: DomainSem, raw: str, names: dict[str, tuple[str, ...]]
    ) -> HeaderReading | None:
        if not self.config.header:
            return None
        return read_header(sem.domain, raw, names)

    def _candidates(
        self, sem: DomainSem, raw: str, readings: HeaderReading | None
    ) -> dict[str, _Reading]:
        """Every field the NAME of this column could mean: V3's rules and names, and the phrases."""
        out: dict[str, _Reading] = {}
        fuzzy: dict[str, _Reading] = {}
        texts = [raw]
        # V3 reads the header as written; the NORMALISED one (camelCase split, glued words cut, a
        # unit set aside) only when it is not the same words
        if (
            readings is not None
            and readings.header.text
            and readings.header.text != raw
            and fold(readings.header.text) != fold(raw)
        ):
            texts.append(readings.header.text)
        for text in texts:
            for candidate in name_candidates(sem, text):
                kind = "RULE" if candidate.name == NameMatch.TOKEN else candidate.name.value
                # a likeness of letters (V3's FUZZY) is kept aside: the phrases do it by WORDS,
                # below, and only when they have nothing for the column does V3's likeness stand
                target = (
                    fuzzy if readings is not None and candidate.name == NameMatch.FUZZY else out
                )
                known = target.get(candidate.field)
                if known is None or candidate.score > known.candidate.score:
                    target[candidate.field] = _Reading(candidate, kind, None)
        if readings is None:
            return out
        # WHO READS A HEADER, in order of authority:
        #   1. a name the kind of data already knows (V3 EXACT): "Imponibile" is a line amount in a
        #      register, "Totale soggiorno" a room revenue - product decisions, never overruled;
        #   2. a phrase of the vocabulary that IS the header (V4 exact / same words reordered): it
        #      beats a bag-of-words rule, which cannot tell "Supplier VAT" (a VAT number) from
        #      "Supplier" (a name) or "Payment status" from "Status";
        #   3. a bag-of-words rule (V3 TOKEN);
        #   4. a phrase that is the header plus a word naming the kind of file, or a spelling
        #      mistake of one: only for a header nothing above read.
        if any(r.candidate.name == NameMatch.EXACT for r in out.values()):
            return out
        matches = {n: m for n, m in readings.matches.items() if n in sem.fields}
        strong = {n: m for n, m in matches.items() if m.kind in (Kind.EXACT, Kind.REORDERED)}
        weak = {n: m for n, m in matches.items() if n not in strong}
        if strong:
            out = {n: r for n, r in out.items() if r.candidate.name != NameMatch.TOKEN}
            chosen = strong
        elif out:
            return out
        else:
            chosen = weak
            if not weak:
                return fuzzy  # nothing the vocabulary reads: V3's likeness of letters, as it was
        words = tokens(readings.header.text)
        for name, match in chosen.items():
            # The rule of V3 this header satisfies for the field (None if no rule does). Two columns
            # that satisfy the SAME rule say the same thing in other words: V3 does not pick one of
            # them (they are CONTESTED, the person is asked), and a reading from the vocabulary must
            # not make that protection disappear ("Issue date" next to "Invoice date").
            rule = (
                rule_index(words, sem.fields[name].rules, sem.context)
                if match.kind in (Kind.EXACT, Kind.REORDERED, Kind.IN_CONTEXT)
                else None
            )
            out[name] = _Reading(
                Candidate(name, _NAME_OF[match.kind], match.score, rule),
                match.kind.value,
                match.phrase,
            )
        return out

    @staticmethod
    def _record(
        table: dict[tuple[int, str], CandidateScore],
        index: int,
        found: _Reading,
        fit: float | None,
        proof: float,
        bonus: float,
        veto: str | None,
        total: float = 0.0,
        notes: tuple[str, ...] = (),
    ) -> None:
        table[(index, found.candidate.field)] = CandidateScore(
            column=index,
            field=found.candidate.field,
            name=found.candidate.name,
            header=found.candidate.score,
            header_kind=found.kind,
            phrase=found.phrase,
            values=fit,
            proof=proof,
            relational=bonus,
            veto=veto,
            total=total,
            rule=found.candidate.rule,
            notes=notes,
        )

    # --- value evidence ---------------------------------------------------------------------------

    def _values_alone(
        self,
        sem: DomainSem,
        samples: Sequence[ColumnSample],
        stats: Sequence[ColumnStats],
        profiles: Sequence[ColumnProfile],
        relational: Relational,
        columns: Sequence[int],
        named: set[int],
        have_name: set[str],
        scored: dict[tuple[int, str], tuple[Candidate, Level]],
        fits: dict[tuple[int, str], float | None],
        totals: dict[tuple[int, str], float],
        table: dict[tuple[int, str], CandidateScore],
        trace: Trace,
    ) -> None:
        domain = sem.domain
        unnamed = [i for i in columns if i not in named]
        # A column is named by its values alone only in a file that already looks like this kind of
        # data (enough fields named by their headers, or a relation between its dates): a marketing
        # report uploaded as bookings has a column of unique codes too, and it is not a
        # booking code.
        supported = len(have_name) >= self.config.support
        # V3's own rule, kept: a field no name points at, whose values fit and that ONE column fits
        single: dict[str, int] = {}
        for key, spec in sem.fields.items():
            if not spec.value_only or key in have_name or spec.fit is None:
                continue
            fitting = [
                i for i in unnamed if stats[i].enough() and spec.fit(stats[i]) >= _VALUE_ONLY_FIT
            ]
            if len(fitting) == 1:
                single[key] = fitting[0]
        for index in unnamed:
            for key, spec in sem.fields.items():
                if key in have_name:
                    continue
                vat = spec.fit(stats[index]) if key == "supplier_vat_number" and spec.fit else 0.0
                proof = 0.0
                kind = semantic_of(domain, key)
                if kind is not None and (domain, key) in PROVABLE:
                    proof = proof_of(profiles[index], kind, vat_fit=vat)
                if not supported:
                    proof = 0.0
                proof = max(proof, relational.proof.get((index, key), 0.0))
                if single.get(key) == index and spec.fit is not None:
                    proof = max(proof, spec.fit(stats[index]))
                if proof < _VALUE_ONLY_FIT:
                    continue
                fit = spec.fit(stats[index]) if spec.fit is not None else None
                evidence = read_values(domain, key, fit, profiles[index], vat_fit=vat)
                bonus = relational.bonus.get((index, key), 0.0)
                total = combine(0.0, fit, proof, bonus, evidence.veto)
                candidate = Candidate(key, NameMatch.VALUES, _VALUE_ONLY_SCORE)
                found = _Reading(candidate, "VALUES", None)
                self._record(
                    table, index, found, fit, proof, bonus, evidence.veto, total, evidence.reasons
                )
                if evidence.veto is not None or total <= 0:
                    continue
                level = level_of(
                    NameMatch.VALUES, _VALUE_ONLY_SCORE, max(proof, fit or 0.0), stats[index]
                )
                scored[(index, key)] = (candidate, level)
                fits[(index, key)] = fit
                totals[(index, key)] = total


__all__ = [
    "CONFIGS",
    "ASSIGN",
    "DEFAULT",
    "HEADER_ONLY",
    "AlgorithmicConfig",
    "AlgorithmicEngine",
    "Trace",
]
