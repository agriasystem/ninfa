"""A person answering Smart Import, one round at a time.

Smart Import asks its questions in turns: what to do about hours in a grid is asked first, the week
after it. The benchmark therefore plays the conversation: after each answer from the system it
gives the answers the TRUTH lists (the ones a careful person would give), re-asks, and goes on until
the import is automatic, the system asks something the truth has no answer for, or nothing new is
asked. Only questions a person could really answer are answered; a question about something the
document does not hold ("which department are all these rows?" for a file that has a department
column) ends the conversation as unresolved.
"""

from datetime import date
from typing import Any

from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from tests.benchmarks.smart_import_v3.match import header_matches, norm
from tests.benchmarks.smart_import_v3.model import Doc, Golden
from tests.benchmarks.smart_import_v3.observe import Observed, OQuestion, run

MAX_ROUNDS = 6
PSEUDO = {"role": "department", "labor_category": "department"}


def _field_of_column(golden: Golden, header: str) -> str | None:
    for name, source in golden.fields.items():
        if source.kind == "COLUMN" and header_matches(source.header, header):
            return name
    return None


def _answer(question: OQuestion, golden: Golden, state: Observed, given: dict[str, Any]) -> bool:
    """Adds the answer to `given`. False when the truth has nothing to say to this question."""
    spec = golden.answers
    kind = question.kind
    if kind == "GRID_HOURS" and "grid_hours" in spec:
        given["grid_hours"] = spec["grid_hours"]
    elif kind == "PERIOD" and "period_start" in spec:
        given["period_start"] = date.fromisoformat(spec["period_start"])
    elif kind == "DATE_ORDER" and "date_order" in spec:
        given["date_order"] = spec["date_order"]
    elif kind == "DECIMAL_STYLE" and "decimal_style" in spec:
        given["decimal_style"] = spec["decimal_style"]
    elif kind == "AMOUNT_BASIS" and "amount_basis" in spec:
        given["amount_basis"] = spec["amount_basis"]
    elif kind == "TABLE" and "table_first_row" in spec:
        choice = next((c for c in question.choices if c[1] == spec["table_first_row"]), None)
        if choice is None:
            return False
        given["table_key"] = choice[0]
    elif kind == "COLUMN_MEANING" and question.column is not None:
        chosen = next(
            (
                item["field"]
                for item in spec.get("column_fields", [])
                if header_matches(tuple(item["header"]), question.column)
                and _occurrence_of(state, question.column) == int(item.get("occurrence", 1))
            ),
            None,
        )
        if chosen is None:
            known = _field_of_column(golden, question.column)
            if known is not None and question.candidate is not None:
                chosen = (
                    question.candidate
                    if PSEUDO.get(question.candidate, question.candidate)
                    == PSEUDO.get(known, known)
                    else None
                )
            elif known is not None:
                chosen = known
        if chosen is None:
            return False
        given.setdefault("column_fields", {})[question.column] = chosen
    elif kind == "VALUE_LABELS" and question.document is not None:
        words: dict[str, str] = {}
        truth = golden.labels.get(question.document, {})
        taught = spec.get("labels", {}).get(question.document, {})
        for label in question.labels:
            meaning = taught.get(label)
            if meaning is None:
                meaning = next(
                    (v for k, v in truth.items() if norm(k) == norm(label) and v != "?"), None
                )
            if meaning is None:
                return False
            words[label] = meaning
        given.setdefault("labels", {}).setdefault(question.document, {}).update(words)
    elif kind == "DEPARTMENT_CONFIRM":
        source = golden.fields.get("department")
        if source is None or source.kind not in {"TITLE", "SHEET", "SECTION"}:
            return False
        given["department_from"] = source.kind
    elif kind == "DEPARTMENT_ROWS" and "department_value" in spec:
        given["department_value"] = spec["department_value"]
    else:
        return False
    return True


def _occurrence_of(state: Observed, header: str) -> int:
    from tests.benchmarks.smart_import_v3.score import _rank

    return _rank(state, header)


def converse(service: UnderstandingService, doc: Doc, first: Observed) -> list[Observed]:
    """The rounds after the first answer (empty when it was already automatic or unanswerable)."""
    rounds: list[Observed] = []
    given: dict[str, Any] = {}
    state = first
    seen = {_signature(first)}
    for _ in range(MAX_ROUNDS):
        if state.automatic or state.error or not state.questions:
            break
        progress = False
        for question in state.questions:
            progress = _answer(question, doc.golden, state, given) or progress
        if not progress:
            break
        try:
            state = run(
                service,
                doc.card,
                doc.filename,
                doc.content,
                answers=UnderstandAnswers(**given),
            )
        except Exception as error:  # an answer the truth built wrongly is the benchmark's bug
            failed = Observed(error=f"answers: {type(error).__name__}: {error}"[:300])
            rounds.append(failed)
            break
        rounds.append(state)
        signature = _signature(state)
        if signature in seen:
            break
        seen.add(signature)
    return rounds


def _signature(state: Observed) -> tuple[Any, ...]:
    return (
        state.level,
        tuple((q.kind, q.column, q.labels) for q in state.questions),
        tuple(state.blocker_codes),
    )
