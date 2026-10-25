"""The answer about a file, passed through the personal-data guard before it is sent anywhere.

`understand` builds a `FileInspection` from a file that may hold names, e-mail addresses, telephone
numbers, tax codes and IBANs. Columns that carry them are left out and never sampled; this is the
second line, and it is server-side: every text the answer would SHOW - example values, department
words, a title, the names of the sheets - is read once more and a personal value found in it is
replaced by a mark (see `app.modules.document_understanding.redaction`).

What the import matches the file by is never touched: headers, field names, question ids, codes
and the decision itself (`proposal`).
"""

from collections.abc import Sequence
from dataclasses import replace

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.proposal import Proposal
from app.modules.data_sources.understanding_types import UnderstandingInfo
from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.redaction import PersonalDataGuard
from app.modules.document_understanding.stats import column_stats
from app.modules.document_understanding.values import text_of


def guard_for(samples: Sequence[ColumnSample], proposal: Proposal) -> PersonalDataGuard:
    """A guard that knows the personal values of THIS file: those of the columns that were found to
    carry them. The values stay in memory for the length of the call and are kept nowhere."""
    columns = [
        (column.pii, [text_of(cell) for cell in sample.values])
        for sample, column in zip(samples, proposal.columns, strict=True)
        if column.pii is not None
    ]
    return PersonalDataGuard.for_columns(columns)


def personal_columns(samples: Sequence[ColumnSample]) -> dict[int, PiiKind]:
    """The columns of a file that carry personal data, by their header and by what their values
    look like (position -> kind)."""
    found: dict[int, PiiKind] = {}
    for sample in samples:
        finding = detect_pii(sample.header, column_stats(sample.values))
        if finding is not None:
            found[sample.position] = finding.kind
    return found


def guard_for_samples(
    samples: Sequence[ColumnSample], personal: dict[int, PiiKind]
) -> PersonalDataGuard:
    """The same guard, for an answer that has no proposal (the plain matching screen)."""
    return PersonalDataGuard.for_columns(
        (personal[sample.position], [text_of(cell) for cell in sample.values])
        for sample in samples
        if sample.position in personal
    )


def redact_inspection(inspection: FileInspection, guard: PersonalDataGuard) -> FileInspection:
    """The inspection with every text that is meant to be SHOWN passed through the guard."""
    understanding = inspection.understanding
    return replace(
        inspection,
        sheet_name=guard.clean_optional(inspection.sheet_name),
        sheet_names=guard.clean_all(inspection.sheet_names),
        columns=tuple(
            replace(column, examples=guard.clean_all(column.examples))
            for column in inspection.columns
        ),
        understanding=None
        if understanding is None
        else _redact_understanding(understanding, guard),
    )


def _redact_understanding(info: UnderstandingInfo, guard: PersonalDataGuard) -> UnderstandingInfo:
    document = info.document
    table = document.table
    if table is not None:
        table = replace(table, sheets=guard.clean_all(table.sheets))
    document = replace(
        document,
        sheets=tuple(replace(sheet, name=guard.clean(sheet.name)) for sheet in document.sheets),
        table=table,
        title=guard.clean_optional(document.title),
    )
    return replace(
        info,
        document=document,
        recognized=tuple(
            replace(item, example=guard.clean_optional(item.example)) for item in info.recognized
        ),
        questions=tuple(
            replace(
                question,
                labels=tuple(
                    replace(label, label=guard.clean(label.label)) for label in question.labels
                ),
                choices=tuple(
                    replace(
                        choice,
                        sheets=guard.clean_all(choice.sheets),
                        title=guard.clean_optional(choice.title),
                    )
                    for choice in question.choices
                ),
            )
            for question in info.questions
        ),
    )


__all__ = ["guard_for", "guard_for_samples", "personal_columns", "redact_inspection"]
