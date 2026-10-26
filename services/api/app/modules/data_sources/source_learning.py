"""Source Learning: Smart Import remembers what a PERSON confirmed about a source, and asks less
the next time - without any model, any embedding or any external service.

    understands -> validates -> maybe asks -> imports -> remembers the confirmation -> asks less

What a source is. A source is `property + kind of data` (the `DataSource` that already exists, one
saved profile each); WITHIN it, the structure of the file: which columns it has, what their values
are like, how they are laid out. NEVER a name, an e-mail, a phone number, a tax code, an IBAN, a
value
of a row, a file name or a note: a column of personal data is only a placeholder in a structure, and
nothing personal is needed to recognise a source.

What is remembered (`Memory`, a small JSON section of the profile's `format_options` - no table, no
migration): the structure of the last file a person confirmed (header keys in order, with the CLASS
of their values), the mapping that was confirmed, the part of it the person decided, the formats
they chose, and a short history of earlier revisions.

When it is trusted. Only a PERSON makes a memory trusted: an explicit answer to a Smart Import
question, or a matching built by hand that was then imported. A file the engine read alone (READY)
is remembered as ENGINE evidence at most and never used to skip a question: the engine cannot teach
itself.

How it is reused. A trusted memory is EVIDENCE, never authority. For each column the person decided,
the current file must still agree: the header is still there (or the engine itself reads another
column as the same field), the values are still of the class they were, they still FIT the field,
and the engine's own reading of this file does not contradict it. What survives is applied as if the
person had answered again; what does not is dropped and reported as a conflict - the current
document
always wins over the memory. Reuse what is still proven, ask what changed.
"""

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.bookings.mapping import normalize_header
from app.modules.data_sources.proposal import Proposal
from app.modules.data_sources.semantics import DomainSem
from app.modules.document_understanding.lexicon import HEADER_STEMS, SECTION_WORDS
from app.modules.document_understanding.pii import looks_like_person
from app.modules.document_understanding.pii_text import normalize
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import fold, stem
from app.modules.document_understanding.values import CellKind

# The placeholder of a column of personal data in a structure: its header is never kept.
PERSONAL = "~"
# A remembered field is believed for a column when its values fit at least this well (0..1).
MIN_FIT = 0.6
# Fewer mapped columns than this share of the remembered ones: not enough proof it is the same
# source.
MIN_COVERAGE = 0.5
HISTORY_KEPT = 5
SCHEMA = 1
# The scalar answers worth remembering: closed vocabularies, nothing from a file.
REMEMBERED_ANSWERS = ("date_order", "decimal_style", "amount_basis", "department_value")


class Trust(StrEnum):
    PERSON = "PERSON"  # a person confirmed it (an answer, or a matching they built)
    ENGINE = "ENGINE"  # only the engine read it: evidence at most, never authority


class Via(StrEnum):
    ANSWERS = "ANSWERS"  # the person answered a Smart Import question
    MANUAL = "MANUAL"  # the person built the matching by hand ("Abbina le colonne")
    ENGINE = "ENGINE"  # nobody decided anything: the engine was READY alone
    REUSE = "REUSE"  # the decision came from the memory itself: nothing new was confirmed


class Drift(StrEnum):
    NONE = "NONE"  # the same structure
    COSMETIC = (
        "COSMETIC"  # harmless: other order, a column renamed to what the engine reads the same
    )
    ADDITIVE = "ADDITIVE"  # new columns, every remembered one still valid
    MISSING = "MISSING"  # a remembered column is gone
    SEMANTIC_CONFLICT = (
        "SEMANTIC_CONFLICT"  # the header says X but the values (or the engine) say not
    )
    MAJOR_CHANGE = "MAJOR_CHANGE"  # not enough in common to call it the same source


class Structure(StrEnum):
    EXACT = "EXACT"  # the verified structure (NONE, COSMETIC)
    COMPATIBLE = "COMPATIBLE"  # probably the same source: reuse what is proven
    DIFFERENT = "DIFFERENT"  # not enough proof: nothing is reused


# --- keys ---


def header_key(header: str) -> str:
    """What a header is compared by: case, accents, punctuation, spacing and invisible characters
    do not matter."""
    return normalize_header(normalize(header))


def value_class(stats: ColumnStats) -> str:
    """The class of a column's values: TEXT, NUMBER, DATE, MIXED (no class holds 80% of them) or
    EMPTY. All that is kept of what a column holds."""
    if stats.n == 0:
        return "EMPTY"
    for kind, name in (
        (CellKind.TEXT, "TEXT"),
        (CellKind.NUMBER, "NUMBER"),
        (CellKind.DATE, "DATE"),
    ):
        if stats.fraction(kind) >= 0.8:
            return name
    return "MIXED"


# --- the memory ---


class Memory(BaseModel):
    """What is kept of a confirmed source. Closed vocabulary and header keys: no value of a file."""

    model_config = ConfigDict(extra="ignore")

    v: int = SCHEMA
    revision: int = 1
    trust: Trust
    origin: Via
    domain: str
    # The structure of the last confirmed file: header keys in order (PERSONAL for a column of
    # personal data) with the class of their values.
    shape: list[tuple[str, str]]
    # The whole confirmed mapping (field -> header key) and the part the PERSON decided.
    mapped: dict[str, str]
    person: dict[str, str] = {}
    answers: dict[str, str] = {}
    history: list[dict[str, Any]] = []
    fingerprint: str = ""

    def header_keys(self) -> list[str]:
        return [key for key, _ in self.shape if key != PERSONAL]

    def kind_of(self, key: str) -> str | None:
        return next((kind for k, kind in self.shape if k == key), None)


def parse_memory(raw: Mapping[str, Any] | None) -> Memory | None:
    """The memory in a stored profile, or None (none, another version, or damaged - which is never
    an error: a source that cannot be remembered is simply read again)."""
    if not raw or not isinstance(raw, Mapping):
        return None
    try:
        memory = Memory.model_validate(dict(raw))
    except (ValidationError, TypeError, ValueError):
        return None
    return memory if memory.v == SCHEMA else None


def fingerprint_of(domain: str, shape: Sequence[tuple[str, str]], mapped: Mapping[str, str]) -> str:
    """A short, deterministic identity of a verified structure (not of any file)."""
    material = json.dumps(
        {
            "d": domain,
            "k": sorted(f"{key}:{kind}" for key, kind in shape if key != PERSONAL),
            "p": sum(1 for key, _ in shape if key == PERSONAL),
            "m": sorted(mapped.items()),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# --- a column of the file being read ---


@dataclass(frozen=True, slots=True)
class ColumnView:
    """One column of the CURRENT file as the matcher needs it: its key, the class of its values,
    what the engine reads it as WITHOUT any memory, and how well its values fit a field."""

    header: str
    key: str
    kind: str  # TEXT | NUMBER | DATE | MIXED | EMPTY
    personal: bool
    field: str | None = None
    level: str | None = None  # HIGH | MEDIUM | LOW
    fit_for: Callable[[str], float | None] = lambda _field: None


def _names_a_person(header: str, sem: DomainSem) -> bool:
    """A header that is a person's name (a roster with one column per employee), unless it is made
    of words NINFA's own vocabulary knows ("Booker Name", "Book Number")."""
    vocabulary = set(HEADER_STEMS) | set(SECTION_WORDS) | set(sem.title_words)
    known = any(stem(word) in vocabulary for word in fold(header).split())
    return looks_like_person(header) and not known


def column_views(sem: DomainSem, proposal: Proposal) -> list[ColumnView]:
    """The columns of a file, read by the engine ALONE (no memory), as the matcher sees them. A
    column the engine locks or flags as personal data, or whose HEADER is a person's name, is a
    placeholder: nothing of it is kept."""
    views: list[ColumnView] = []
    for column in proposal.columns:

        def fit_for(field: str, stats: ColumnStats = column.stats) -> float | None:
            spec = sem.fields.get(field)
            return None if spec is None or spec.fit is None else spec.fit(stats)

        views.append(
            ColumnView(
                header=column.header,
                key=header_key(column.header),
                kind=value_class(column.stats),
                personal=(
                    column.pii is not None
                    or column.locked is not None
                    or _names_a_person(column.header, sem)
                ),
                field=column.field,
                level=None if column.level is None else column.level.value,
                fit_for=fit_for,
            )
        )
    return views


def shape_of(columns: Sequence[ColumnView]) -> list[tuple[str, str]]:
    return [(PERSONAL if c.personal else c.key, c.kind) for c in columns if c.personal or c.key]


# --- matching ---


@dataclass(frozen=True, slots=True)
class Conflict:
    header: str
    field: str
    reason: (
        str  # PERSONAL_DATA | ENGINE_DISAGREES | VALUE_CLASS | VALUES_DONT_FIT | DUPLICATE_HEADER
    )


@dataclass(frozen=True, slots=True)
class SourceMatch:
    structure: Structure
    drift: Drift
    # How much of the two structures coincide (0..1), and the numbers behind it.
    score: float
    coincide: int
    known: int
    current: int
    # current header -> field: what the PERSON decided and the file still proves.
    proven: Mapping[str, str]
    # current header -> the remembered key it was renamed from (the engine reads it as that field).
    renamed: Mapping[str, str]
    missing: tuple[tuple[str, str], ...]  # (field, remembered key) no longer in the file
    conflicts: tuple[Conflict, ...]
    new_columns: int
    reordered: bool
    evidence: tuple[str, ...]

    def explain(self) -> str:
        """Why this file is, or is not, the remembered source, in a sentence (logs and tests)."""
        parts = [
            f"{self.coincide}/{max(self.known, self.current)} columns coincide",
            f"{self.new_columns} new",
            f"{len(self.missing)} missing",
            f"{len(self.conflicts)} in conflict",
        ]
        if self.renamed:
            parts.append(f"{len(self.renamed)} renamed")
        types = "types compatible" if not self.conflicts else "types NOT all compatible"
        return (
            f"{self.structure.value} ({self.drift.value}): "
            + ", ".join(parts)
            + f"; {types}; score {self.score:.2f}"
        )


def _disagreement(memory: Memory, field: str, key: str, column: ColumnView) -> str | None:
    """Why this column can no longer be what the memory says it is, or None."""
    if column.personal:
        return "PERSONAL_DATA"
    if column.field is not None and column.field != field and column.level == "HIGH":
        return "ENGINE_DISAGREES"  # the current document says something else, and says it clearly
    recorded = memory.kind_of(key)
    if column.kind == "MIXED" and recorded in {"TEXT", "NUMBER", "DATE"}:
        return "VALUE_CLASS"
    if (
        recorded in {"TEXT", "NUMBER", "DATE"}
        and column.kind in {"TEXT", "NUMBER", "DATE"}
        and column.kind != recorded
    ):
        return "VALUE_CLASS"
    fit = column.fit_for(field)
    if fit is not None and fit < MIN_FIT:
        return "VALUES_DONT_FIT"
    return None


def match_source(memory: Memory, columns: Sequence[ColumnView]) -> SourceMatch:
    """Compare a remembered structure with the file in front of us. Deterministic and explainable:
    no score decides anything by itself - what is reused is decided column by column."""
    named = [c for c in columns if not c.personal and c.key]
    counts: dict[str, int] = {}
    for each in named:
        counts[each.key] = counts.get(each.key, 0) + 1
    by_key = {c.key: c for c in named if counts[c.key] == 1}

    used: set[str] = set()
    found: dict[str, tuple[ColumnView, str]] = {}  # field -> (column, remembered key)
    renamed: dict[str, str] = {}
    missing: list[tuple[str, str]] = []
    conflicts: list[Conflict] = []
    pending: list[tuple[str, str]] = []
    for field, key in memory.mapped.items():
        column = by_key.get(key)
        if column is None and counts.get(key, 0) > 1:
            duplicate = next(c for c in named if c.key == key)
            conflicts.append(Conflict(duplicate.header, field, "DUPLICATE_HEADER"))
            used.update(c.header for c in named if c.key == key)
        elif column is None:
            pending.append((field, key))
        else:
            used.add(column.header)
            found[field] = (column, key)
    # A header renamed to what the engine reads the same is followed only when the structure is
    # already anchored by names: with nothing in common, "the engine reads every column" proves
    # that the file is readable, not that it is this source.
    anchored = len(found) >= max(1, math.ceil(len(memory.mapped) * MIN_COVERAGE))
    for field, key in pending:
        column = _alias_of(field, key, named, memory, used) if anchored else None
        if column is None:
            missing.append((field, key))
            continue
        renamed[column.header] = key
        used.add(column.header)
        found[field] = (column, key)

    proven: dict[str, str] = {}
    for field, (column, key) in found.items():
        reason = _disagreement(memory, field, key, column)
        if reason is not None:
            conflicts.append(Conflict(column.header, field, reason))
        elif field in memory.person:
            proven[column.header] = field

    known_keys = set(memory.header_keys())
    current_keys = {c.key for c in named}
    fresh = [c for c in named if c.header not in used and c.key not in known_keys]
    coincide = len(known_keys & current_keys) + len(renamed)
    union = len(known_keys | current_keys) - len(renamed)
    score = coincide / union if union else 1.0
    shared = [k for k in memory.header_keys() if k in current_keys]
    order_now = [c.key for c in named if c.key in known_keys]
    reordered = bool(shared) and [k for k in order_now if k in shared] != shared

    total = len(memory.mapped)
    present = len(found) + sum(1 for c in conflicts if c.reason == "DUPLICATE_HEADER")
    if total and present < max(1, math.ceil(total * MIN_COVERAGE)):
        drift = Drift.MAJOR_CHANGE
    elif conflicts:
        drift = Drift.SEMANTIC_CONFLICT
    elif missing:
        drift = Drift.MISSING
    elif fresh:
        drift = Drift.ADDITIVE
    elif renamed or reordered:
        drift = Drift.COSMETIC
    else:
        drift = Drift.NONE
    structure = (
        Structure.DIFFERENT
        if drift == Drift.MAJOR_CHANGE
        else Structure.EXACT
        if drift in (Drift.NONE, Drift.COSMETIC)
        else Structure.COMPATIBLE
    )
    evidence = [f"MAPPED_FOUND:{len(found)}/{total}"]
    if known_keys == current_keys:
        evidence.append("EXACT_HEADER_SET")
    if reordered:
        evidence.append("ORDER_CHANGED")
    if renamed:
        evidence.append(f"KNOWN_ALIAS:{len(renamed)}")
    if missing:
        evidence.append(f"MISSING_KNOWN_COLUMN:{len(missing)}")
    if fresh:
        evidence.append(f"NEW_COLUMN:{len(fresh)}")
    if conflicts:
        evidence.extend(sorted({f"CONFLICT:{c.reason}" for c in conflicts}))
    else:
        evidence.append("TYPES_COMPATIBLE")
    return SourceMatch(
        structure=structure,
        drift=drift,
        score=round(score, 3),
        coincide=coincide,
        known=len(known_keys),
        current=len(current_keys),
        proven=proven,
        renamed=renamed,
        missing=tuple(missing),
        conflicts=tuple(conflicts),
        new_columns=len(fresh),
        reordered=reordered,
        evidence=tuple(evidence),
    )


def _alias_of(
    field: str, key: str, columns: Sequence[ColumnView], memory: Memory, used: set[str]
) -> ColumnView | None:
    """A column that is not the remembered one by name, but that the engine ITSELF reads as that
    same field, with values of the class it had: the same source, a harmlessly different header."""
    known = set(memory.header_keys())
    candidates = [
        c
        for c in columns
        if c.header not in used
        and c.key not in known  # not a known column of another meaning
        and c.field == field
        and c.level in {"HIGH", "MEDIUM"}
    ]
    return candidates[0] if len(candidates) == 1 else None


def reusable(memory: Memory, match: SourceMatch) -> bool:
    """May this memory pre-answer anything? Only a person's confirmation, and only for a structure
    that is the same source (or probably is)."""
    return memory.trust == Trust.PERSON and match.structure != Structure.DIFFERENT


def kept_answers(memory: Memory, match: SourceMatch) -> dict[str, str]:
    """The person's earlier scalar answers, for a file that still looks like the same source."""
    if not reusable(memory, match) or match.drift in (Drift.SEMANTIC_CONFLICT, Drift.MISSING):
        return {}
    return dict(memory.answers)


@dataclass(frozen=True, slots=True)
class LearningInfo:
    """What Source Learning did for THIS file. Internal: it is never part of the API response."""

    memory: Memory | None = None
    match: SourceMatch | None = None
    # The current headers whose meaning came from the memory (the person is not asked again).
    reused: tuple[str, ...] = ()
    # The structure of this file: what a confirmed import remembers.
    shape: tuple[tuple[str, str], ...] = ()
    # What the engine reads each column as ALONE: (header, field, level). A person's answer decides
    # something only where it differs from this.
    engine: tuple[tuple[str, str | None, str | None], ...] = ()


@dataclass(frozen=True, slots=True)
class Confirmation:
    """How the decision being imported was CONFIRMED - the only thing that can make a memory
    trusted. Built by the server from its own reading, never from a claim of the client."""

    origin: Via
    # The scalar answers the person gave (closed vocabularies only).
    answers: Mapping[str, str]
    # The header keys the person classified by answering (ANSWERS); a matching by hand (MANUAL)
    # is the person's whole decision.
    classified: frozenset[str]
    # The structure of the file that was imported.
    shape: tuple[tuple[str, str], ...]


# --- remembering ---


def remember(
    existing: Memory | None,
    *,
    domain: str,
    shape: Sequence[tuple[str, str]],
    mapped: Mapping[str, str],
    person: Mapping[str, str],
    answers: Mapping[str, str],
    origin: Via,
) -> Memory | None:
    """The memory after an import that succeeded, or None when nothing is to be saved.

    * A person's confirmation (answers, a matching by hand) makes the memory TRUSTED. If it says
      something different from what was remembered, it is a NEW REVISION: the new confirmation
      prevails and the old one stays in a short history, never silently overwritten.
    * The engine alone (READY, nobody decided anything) never replaces what a person confirmed, and
      only ever leaves ENGINE evidence behind.
    * A decision that came from the memory itself confirms nothing new: nothing changes.
    """
    if origin == Via.REUSE:
        return None
    trust = Trust.PERSON if origin in (Via.ANSWERS, Via.MANUAL) else Trust.ENGINE
    if trust == Trust.ENGINE and existing is not None and existing.trust == Trust.PERSON:
        return None
    mapped_now = dict(mapped)
    person_now = dict(person) if trust == Trust.PERSON else {}
    answers_now = {k: v for k, v in answers.items() if k in REMEMBERED_ANSWERS and v}
    fingerprint = fingerprint_of(domain, shape, mapped_now)
    history: list[dict[str, Any]] = []
    revision = 1
    if existing is not None:
        history = list(existing.history)
        same = (
            existing.trust == trust
            and existing.mapped == mapped_now
            and existing.person == person_now
            and existing.answers == answers_now
        )
        if same:
            revision = existing.revision
        else:
            revision = existing.revision + 1
            history.append(
                {
                    "revision": existing.revision,
                    "trust": existing.trust.value,
                    "origin": existing.origin.value,
                    "mapped": existing.mapped,
                    "person": existing.person,
                }
            )
    return Memory(
        revision=revision,
        trust=trust,
        origin=origin,
        domain=domain,
        shape=list(shape),
        mapped=mapped_now,
        person=person_now,
        answers=answers_now,
        history=history[-HISTORY_KEPT:],
        fingerprint=fingerprint,
    )


def stored(memory: Memory) -> dict[str, Any]:
    """The memory as the JSON kept in the profile."""
    return memory.model_dump(mode="json")


__all__ = [
    "HISTORY_KEPT",
    "LearningInfo",
    "MIN_COVERAGE",
    "MIN_FIT",
    "PERSONAL",
    "REMEMBERED_ANSWERS",
    "ColumnView",
    "Confirmation",
    "Conflict",
    "Drift",
    "Memory",
    "Via",
    "SourceMatch",
    "Structure",
    "Trust",
    "column_views",
    "fingerprint_of",
    "header_key",
    "kept_answers",
    "match_source",
    "parse_memory",
    "remember",
    "reusable",
    "shape_of",
    "stored",
    "value_class",
]
