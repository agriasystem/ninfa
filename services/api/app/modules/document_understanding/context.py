"""The lines above a table: which say something ABOUT the table, and which are something else.

A staff sheet starts with a block like

    Reparto:      Spa e benessere
    Periodo:      19-25 ottobre 2026
    Responsabile: Direzione

and a title ("TURNI HOUSEKEEPING"), sometimes a free note ("Nota: Spa chiusa lunedi"), sometimes a
name. What each line is decides what it may be used for: the department stated by a label that
says "department" belongs to the rows below it; the same word after "Nota:", "Cliente:" or
"Responsabile:" belongs to nothing - a note, a customer, a person. The LABEL decides, never the
value: a word that happens to be a department is not one because it appears somewhere.

Deterministic and closed: a label the vocabulary does not know is simply a line like any other.
Personal data (a person's name after "Responsabile:") is only ever recognised so that it is left
out; this module returns the kind of a line and its parts, and callers never show the value.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.modules.document_understanding.text import stems, tokens


class LabelKind(StrEnum):
    DEPARTMENT = "DEPARTMENT"  # what the rows below belong to
    PERIOD = "PERIOD"  # the week / month the file is about
    PROPERTY = "PROPERTY"  # the hotel / structure / company
    PERSON = "PERSON"  # who compiled it / who is in charge: personal data, never read
    PARTY = "PARTY"  # a customer / a supplier / a guest: not a department of the rows
    NOTE = "NOTE"  # a free note, a legend, a warning


_LABEL_WORDS: dict[LabelKind, frozenset[str]] = {
    LabelKind.DEPARTMENT: stems("reparto dipartimento department dept area settore team uo"),
    LabelKind.PERIOD: stems("periodo period settimana week mese month anno year data date dal al"),
    LabelKind.PROPERTY: stems("struttura hotel albergo property esercizio azienda societa company"),
    LabelKind.PERSON: stems(
        "responsabile referente manager supervisore compilato redatto autore preparato operatore "
        "dipendente nome cognome name"
    ),
    LabelKind.PARTY: stems("cliente clienti customer ospite guest fornitore supplier"),
    LabelKind.NOTE: stems(
        "nota note notes annotazioni annotazione commento commenti legenda avviso attenzione "
        "warning remark remarks"
    ),
}
# The first label of a line wins in this order: "Nota cliente:" is a note.
_ORDER = (
    LabelKind.NOTE,
    LabelKind.PERSON,
    LabelKind.PARTY,
    LabelKind.DEPARTMENT,
    LabelKind.PERIOD,
    LabelKind.PROPERTY,
)
_LINE = re.compile(r"^\s*(?P<label>[^:\n]{1,40}?)\s*:\s*(?P<value>\S.*)$")


@dataclass(frozen=True, slots=True)
class ContextLine:
    """A line of the lines above a table. `kind` is None for a label nobody knows and for a line
    that is not a label/value pair at all (a title)."""

    text: str
    kind: LabelKind | None = None
    label: str = ""
    value: str = ""

    @property
    def is_title(self) -> bool:
        return not self.label


def kind_of_label(label: str) -> LabelKind | None:
    words = tokens(label)
    for kind in _ORDER:
        if _LABEL_WORDS[kind] & words:
            return kind
    return None


def read_line(text: str) -> ContextLine:
    match = _LINE.match(text)
    if match is None:
        return ContextLine(text)
    label, value = match.group("label"), match.group("value").strip()
    return ContextLine(text, kind_of_label(label), label, value)


def read_context(lines: list[str] | tuple[str, ...]) -> list[ContextLine]:
    return [read_line(line) for line in lines]


def stated_department_values(lines: list[str] | tuple[str, ...]) -> list[str]:
    """The values of the lines whose label says "department": nothing else says it."""
    return [
        line.value
        for line in read_context(lines)
        if line.kind == LabelKind.DEPARTMENT and line.value
    ]


def title_lines(lines: list[str] | tuple[str, ...]) -> list[str]:
    """The lines that may be read as a TITLE: those that are not a label/value pair about
    something else (a person, a customer, a note, a period, a hotel). A pair whose label nobody
    knows ("Turni: Housekeeping") is still read as it always was."""
    return [line.text for line in read_context(lines) if line.is_title or line.kind is None]


__all__ = [
    "ContextLine",
    "LabelKind",
    "kind_of_label",
    "read_context",
    "read_line",
    "stated_department_values",
    "title_lines",
]
