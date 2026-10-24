"""Deterministic "which column means what" suggestions, shared by every file domain.

No AI, no learning, no network: a header is compared (case, accents and punctuation ignored) with
the known names of each field, first exactly, then by similarity. A suggestion is only a proposal
shown to the customer: it never becomes a mapping by itself, only an explicitly confirmed one does.

The ranking is the one the booking import has always had (`app.modules.bookings.suggestions` now
delegates here, so its behaviour is unchanged); each domain only brings its own field list, its own
known names and, if needed, headers that must NEVER be suggested.
"""

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.bookings.mapping import normalize_header


class SuggestionConfidence(StrEnum):
    HIGH = "HIGH"  # the header is a known name of the field
    MEDIUM = "MEDIUM"  # very similar to a known name
    LOW = "LOW"  # somewhat similar to a known name
    NONE = "NONE"  # nothing suggested


class SuggestionReason(StrEnum):
    KNOWN_ALIAS = "KNOWN_ALIAS"
    FUZZY_MATCH = "FUZZY_MATCH"
    NO_MATCH = "NO_MATCH"


MEDIUM_THRESHOLD = 0.88
LOW_THRESHOLD = 0.78


@dataclass(frozen=True)
class FieldSuggestion[FieldT: StrEnum]:
    field: FieldT
    column: str | None
    confidence: SuggestionConfidence
    reason: SuggestionReason
    score: float = 0.0


@dataclass(frozen=True)
class _Candidate[FieldT: StrEnum]:
    field: FieldT
    header: str
    score: float
    exact: bool


def normalise_aliases[FieldT: StrEnum](
    aliases: Mapping[FieldT, tuple[str, ...]],
) -> dict[FieldT, tuple[str, ...]]:
    return {
        field: tuple(normalize_header(alias) for alias in names) for field, names in aliases.items()
    }


def suggest_fields[FieldT: StrEnum](
    headers: Sequence[str],
    *,
    aliases: Mapping[FieldT, tuple[str, ...]],
    order: Sequence[FieldT],
    excluded: frozenset[str] = frozenset(),
) -> list[FieldSuggestion[FieldT]]:
    """One suggestion per field (in `order`), each header used at most once.

    Known names outrank fuzzy matches; among equals the field order and the file's column order
    decide, so the result is fully deterministic. A header whose normalised form is in `excluded`
    is never suggested (a column that looks like a field but means something else).
    """
    normalised = normalise_aliases(aliases)
    position_of_field = {field: position for position, field in enumerate(order)}
    column = {header: position for position, header in reversed(list(enumerate(headers)))}

    candidates: list[_Candidate[FieldT]] = []
    for header in headers:
        key = normalize_header(header)
        if not key or key in excluded:
            continue
        for field, names in normalised.items():
            if key in names:
                candidates.append(_Candidate(field, header, 1.0, exact=True))
                continue
            best = max(difflib.SequenceMatcher(None, key, name).ratio() for name in names)
            if best >= LOW_THRESHOLD:
                candidates.append(_Candidate(field, header, best, exact=False))
    ranked = sorted(
        candidates,
        key=lambda c: (not c.exact, -c.score, position_of_field[c.field], column[c.header]),
    )

    chosen: dict[FieldT, _Candidate[FieldT]] = {}
    used_headers: set[str] = set()
    for candidate in ranked:
        if candidate.field in chosen or candidate.header in used_headers:
            continue
        chosen[candidate.field] = candidate
        used_headers.add(candidate.header)

    suggestions: list[FieldSuggestion[FieldT]] = []
    for field in order:
        pick = chosen.get(field)
        if pick is None:
            suggestions.append(
                FieldSuggestion(field, None, SuggestionConfidence.NONE, SuggestionReason.NO_MATCH)
            )
        elif pick.exact:
            suggestions.append(
                FieldSuggestion(
                    field,
                    pick.header,
                    SuggestionConfidence.HIGH,
                    SuggestionReason.KNOWN_ALIAS,
                    1.0,
                )
            )
        else:
            confidence = (
                SuggestionConfidence.MEDIUM
                if pick.score >= MEDIUM_THRESHOLD
                else SuggestionConfidence.LOW
            )
            suggestions.append(
                FieldSuggestion(
                    field, pick.header, confidence, SuggestionReason.FUZZY_MATCH, pick.score
                )
            )
    return suggestions


__all__ = [
    "LOW_THRESHOLD",
    "MEDIUM_THRESHOLD",
    "FieldSuggestion",
    "SuggestionConfidence",
    "SuggestionReason",
    "normalise_aliases",
    "suggest_fields",
]
