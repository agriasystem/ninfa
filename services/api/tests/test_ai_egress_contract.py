"""The AI egress contract: what may leave the server towards a model, and the gate that enforces it.

The model may be shown the SHAPE of a file - safe header labels, kinds of values, counts, the class
(never a value) of a personal-data column, a few cleaned example words - and nothing else. The gate
does not trust whoever built the evidence: it cleans every text again, shrinks the document under a
hard limit by sending LESS, reads the final text once more, and when anything personal is still
there it makes no call at all. A provider is never asked to protect anything.

No database, no network, no model: a stand-in provider reads what it is handed and audits it.
"""

import json
import logging
import socket
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from app.modules.ai.import_understanding import egress
from app.modules.ai.import_understanding import resolver as resolver_module
from app.modules.ai.import_understanding.egress import (
    MAX_PAYLOAD_CHARS,
    EgressGuard,
    EgressTooLargeError,
    EgressViolationError,
    fit_budget,
    prepare,
    verify,
)
from app.modules.ai.import_understanding.prompt import SYSTEM_INSTRUCTIONS, evidence_json
from app.modules.ai.import_understanding.resolver import (
    MAX_CALLS,
    ImportUnderstandingResolver,
)
from app.modules.ai.import_understanding.sanitize import REMOVED
from app.modules.ai.import_understanding.types import (
    AiResolution,
    ColumnEvidence,
    OfferedQuestion,
    ResolutionReason,
    UnderstandingEvidence,
)
from app.modules.ai.import_understanding.validator import FitOf
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from app.modules.data_sources.understanding_ai import egress_guard
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.redaction import PersonalDataGuard
from app.modules.ingestion.models import DataSourceDomain
from tests.hardening_support import PEOPLE, staff, xlsx
from tests.import_ai_support import Recorder, Scenario, ScenarioProvider, understand_with

SEMANTICS = {
    DataSourceDomain.BOOKINGS: BOOKINGS,
    DataSourceDomain.LABOR: LABOR,
    DataSourceDomain.COSTS: COSTS,
}
FIELDS = {
    "BOOKINGS": ("check_in", "check_out", "channel"),
    "LABOR": ("work_date", "role", "planned_hours", "actual_hours"),
    "COSTS": ("invoice_number", "line_total"),
}


def _evidence(**overrides: object) -> UnderstandingEvidence:
    base: dict[str, object] = {
        "expected_domain": "LABOR",
        "fields": FIELDS,
        "columns": (
            ColumnEvidence(0, "Giorno", "DATE", 10, 10),
            ColumnEvidence(1, "Gruppo", "TEXT", 10, 3, samples=("Reception", "Cucina")),
            ColumnEvidence(2, "Ore", "NUMBER", 10, 4, number_range=("4", "8")),
        ),
        "questions": (OfferedQuestion("DOMAIN", "DOMAIN", ("BOOKINGS", "LABOR", "COSTS")),),
    }
    base.update(overrides)
    return UnderstandingEvidence(**base)  # type: ignore[arg-type]


def _fit(_domain: str, _index: int, _field: str) -> float | None:
    return 1.0


# --- 1. every free text is cleaned again from scratch ---


def test_the_gate_cleans_texts_the_builder_forgot_to() -> None:
    dirty = _evidence(
        title="turni di mario.rossi@example.com",
        sheets=(("IT60X0542811101000000123456", "TABLE", 12),),
        columns=(
            ColumnEvidence(
                0, "chiama +39 333 1234567", "TEXT", 5, 2, samples=("RSSMRA85T10A562S",)
            ),
        ),
    )

    clean, removed = prepare(dirty, EgressGuard())

    seen = evidence_json(clean)
    for secret in ("mario.rossi", "IT60X05428", "333 1234567", "RSSMRA85T10A562S"):
        assert secret not in seen
    assert removed == 4 and seen.count(REMOVED) == 4
    verify(seen, EgressGuard())  # and the gate itself agrees it is clean


def test_a_header_that_is_the_name_of_a_person_is_not_a_safe_label() -> None:
    # a staff grid has one column per employee
    dirty = _evidence(
        columns=(
            ColumnEvidence(0, "Mario Rossi", "NUMBER", 7, 4, number_range=("0", "8")),
            ColumnEvidence(1, "Giulia", "NUMBER", 7, 4),
            ColumnEvidence(2, "Ore", "NUMBER", 7, 4),
        )
    )

    clean, _ = prepare(dirty, EgressGuard())

    assert [c.header for c in clean.columns] == [REMOVED, REMOVED, "Ore"]


def test_the_production_guard_keeps_a_label_made_of_words_ninfa_knows() -> None:
    guard = egress_guard(PersonalDataGuard(), SEMANTICS)
    evidence = _evidence(
        columns=(
            ColumnEvidence(0, "Book Number", "TEXT", 7, 7),
            ColumnEvidence(1, "Booker Name", "TEXT", 7, 7, pii="PII_PERSON_NAME"),
            ColumnEvidence(2, "Mario Rossi", "NUMBER", 7, 4),
        )
    )

    clean, _ = prepare(evidence, guard)

    assert [c.header for c in clean.columns] == ["Book Number", "Booker Name", REMOVED]


def test_a_personal_value_of_the_file_cannot_ride_in_a_header_a_sheet_or_an_example() -> None:
    guard = EgressGuard(
        scrub=PersonalDataGuard.for_columns([(PiiKind.PERSON_NAME, ["Giulia Ferretti"])]).clean
    )
    dirty = _evidence(
        sheets=(("Ferretti Giulia", "TABLE", 9),),
        title="Giulia Ferretti",
        columns=(
            ColumnEvidence(0, "Resp. Giulia Ferretti", "TEXT", 5, 2, samples=("Giulia Ferretti",)),
            ColumnEvidence(1, "Gruppo", "TEXT", 5, 2, samples=("Reception", "Cucina")),
        ),
    )

    clean, removed = prepare(dirty, guard)

    seen = evidence_json(clean)
    assert "Ferretti" not in seen and "Giulia" not in seen
    assert removed >= 4
    assert "Reception" in seen  # what is not personal stays


def test_a_personal_column_is_only_its_class_never_a_value() -> None:
    leaky = _evidence(
        columns=(
            ColumnEvidence(0, "Cognome", "TEXT", 5, 5, pii="PII_PERSON_NAME", samples=("Rossi",)),
            ColumnEvidence(1, "Boh", "TEXT", 5, 5, pii="SOMETHING_NEW", samples=("Verdi",)),
            ColumnEvidence(2, "Tel", "NUMBER", 5, 5, pii="PII_PHONE", number_range=("1", "9")),
        )
    )

    clean, _ = prepare(leaky, EgressGuard())

    assert all(c.samples == () and c.number_range is None for c in clean.columns)
    assert [c.pii for c in clean.columns] == ["PII_PERSON_NAME", "PII_PERSON_NAME", "PII_PHONE"]


@pytest.mark.parametrize(
    ("bounds", "kept"),
    [
        (("0", "24"), True),
        (("-120.5", "9999.99"), True),
        (("1234567", "7654321"), True),
        (("3201234567", "3999999999"), False),  # could be somebody's mobile number
        (("12345678", "9"), False),
        (("1e9", "2"), False),
    ],
)
def test_a_range_is_shown_only_when_it_cannot_be_somebodys_telephone_number(
    bounds: tuple[str, str], kept: bool
) -> None:
    evidence = _evidence(
        columns=(ColumnEvidence(0, "Valore", "NUMBER", 5, 5, number_range=bounds),)
    )

    clean, _ = prepare(evidence, EgressGuard())

    assert (clean.columns[0].number_range == bounds) is kept


def test_a_question_whose_choice_the_cleaning_would_change_is_not_offered() -> None:
    evidence = _evidence(
        questions=(
            OfferedQuestion("DOMAIN", "DOMAIN", ("BOOKINGS", "LABOR")),
            OfferedQuestion("TABLE", "TABLE", ("Foglio1", "scrivere a a.b@example.com")),
            OfferedQuestion("bad id!", "TABLE", ("x",)),
        )
    )

    clean, _ = prepare(evidence, EgressGuard())

    assert [q.id for q in clean.questions] == ["DOMAIN"]


def test_a_field_nobody_offered_is_not_passed_on_as_already_placed() -> None:
    evidence = _evidence(columns=(ColumnEvidence(0, "Boh", "TEXT", 5, 5, assigned="<script>"),))

    clean, _ = prepare(evidence, EgressGuard())

    assert clean.columns[0].assigned is None


# --- 2. one last read of the final text


@pytest.mark.parametrize(
    ("leak", "code"),
    [
        ("scrivi a mario.rossi@example.com", "EMAIL"),
        ("IT60 X054 2811 1010 0000 0123 456", "IBAN"),
        ("RSSMRA85T10A562S", "TAX_CODE"),
        ("+39 333 1234567", "PHONE"),
    ],
)
def test_the_final_text_is_read_once_more_and_a_leak_makes_the_call_impossible(
    leak: str, code: str
) -> None:
    document = json.dumps({"columns": [{"header": leak}]}, ensure_ascii=False)

    with pytest.raises(EgressViolationError) as caught:
        verify(document, EgressGuard())

    assert code in caught.value.codes
    assert leak not in str(caught.value)  # the codes are words, never the content


def test_a_personal_value_of_the_file_in_the_final_text_makes_the_call_impossible() -> None:
    guard = EgressGuard(
        scrub=PersonalDataGuard.for_columns([(PiiKind.PERSON_NAME, ["Giulia Ferretti"])]).clean
    )

    with pytest.raises(EgressViolationError) as caught:
        verify('{"columns":[{"header":"Resp. Giulia Ferretti"}]}', guard)

    assert caught.value.codes == ("FILE_VALUE",)


def test_a_hidden_leak_in_the_final_text_is_found_too() -> None:
    hidden = "mario.ro​ssi@exam​ple.com"

    with pytest.raises(EgressViolationError):
        verify(json.dumps({"x": hidden}), EgressGuard())


def test_when_the_gate_upstream_is_broken_the_provider_is_not_called_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # simulate the bug the last read exists for: the cleaning step lets a leak through
    leaky = _evidence(
        columns=(ColumnEvidence(0, "Contatto mario.rossi@example.com", "TEXT", 5, 5),)
    )
    monkeypatch.setattr(resolver_module, "prepare", lambda evidence, guard: (evidence, 0))
    spy = Recorder()

    result = ImportUnderstandingResolver(spy).resolve(leaky, _fit)

    assert result.reason == ResolutionReason.BLOCKED and result.calls == 0 and not result.used
    assert spy.requests == []


def test_a_provider_is_only_ever_handed_text_that_has_been_through_the_gate() -> None:
    dirty = _evidence(
        columns=(
            ColumnEvidence(0, "Mario Rossi", "TEXT", 5, 5, samples=("mario.rossi@example.com",)),
            ColumnEvidence(1, "Gruppo", "TEXT", 5, 3, samples=("Reception",)),
        )
    )
    spy = Recorder(forbidden=("mario.rossi", "Mario Rossi"))

    ImportUnderstandingResolver(spy).resolve(dirty, _fit)

    assert len(spy.requests) == 1 and spy.violations == []
    request = spy.requests[0]
    assert request.system_instructions == SYSTEM_INSTRUCTIONS  # static, trusted, no evidence in it


# --- 3. a hard limit, reached by sending less


def _wide(columns: int, samples: int = 6) -> UnderstandingEvidence:
    return _evidence(
        columns=tuple(
            ColumnEvidence(
                i,
                f"Colonna numero {i} con un nome un po' lungo",
                "TEXT",
                50,
                10,
                samples=tuple(f"parola{i}-{j} " + "x" * 25 for j in range(samples)),
                assigned="work_date" if i == 0 else ("role" if i % 7 == 0 else None),
            )
            for i in range(columns)
        )
    )


def test_a_wide_workbook_is_reduced_under_the_limit_and_never_grown() -> None:
    evidence, _ = prepare(_wide(60), EgressGuard())
    assert len(evidence_json(evidence)) > MAX_PAYLOAD_CHARS

    fitted, reduced = fit_budget(evidence)

    assert reduced and len(evidence_json(fitted)) <= MAX_PAYLOAD_CHARS
    original = {c.index: c for c in evidence.columns}
    assert all(c.index in original for c in fitted.columns)
    for column in fitted.columns:  # nothing was added, only taken away
        assert set(column.samples) <= set(original[column.index].samples)
        assert column.header == original[column.index].header


def test_the_reduction_is_the_same_every_time_for_the_same_document() -> None:
    evidence, _ = prepare(_wide(60), EgressGuard())

    first, _ = fit_budget(evidence)
    second, _ = fit_budget(evidence)

    assert evidence_json(first) == evidence_json(second)


def test_a_document_under_the_limit_is_sent_as_it_is() -> None:
    evidence, _ = prepare(_evidence(), EgressGuard())

    fitted, reduced = fit_budget(evidence)

    assert not reduced and fitted == evidence


def test_columns_the_rules_already_placed_leave_before_the_ones_still_open() -> None:
    evidence, _ = prepare(_wide(60, samples=0), EgressGuard())
    fitted, _ = fit_budget(evidence, limit=len(evidence_json(evidence)) - 400)

    open_before = {c.index for c in evidence.columns if c.assigned is None}
    open_after = {c.index for c in fitted.columns if c.assigned is None}
    assert open_after == open_before  # the people who need the model's help keep their columns


def test_when_even_the_minimum_does_not_fit_nothing_is_sent() -> None:
    huge = _evidence(fields={"LABOR": tuple(f"field_{i}" for i in range(2000))})
    spy = Recorder()

    result = ImportUnderstandingResolver(spy).resolve(huge, _fit)

    assert result.reason == ResolutionReason.TOO_LARGE and spy.requests == []
    with pytest.raises(EgressTooLargeError):
        fit_budget(prepare(huge, EgressGuard())[0])


# --- 4. what a file costs depends on the document, not on its rows


def _staff_file(days: int) -> bytes:
    rows = staff(["Giorno", "Nome e cognome", "Gruppo di lavoro", "Ore previste", "Ore"], days=days)
    return xlsx(rows)


def test_the_cost_of_a_file_does_not_grow_with_its_rows() -> None:
    sizes: list[int] = []
    for days in (3, 60, 400):
        model = Recorder(forbidden=PEOPLE)
        understand_with(model, DataSourceDomain.LABOR, _staff_file(days), date_order="DMY")
        assert len(model.requests) <= 1, "one call per file, never one per row or per column"
        assert model.violations == []
        sizes.extend(len(r.evidence_json) for r in model.requests)

    assert sizes, "the file has a column the rules cannot place"
    assert max(sizes) - min(sizes) < 60  # only the digits of the counts differ
    assert max(sizes) <= MAX_PAYLOAD_CHARS


def test_a_model_that_never_answers_properly_is_asked_twice_and_no_more() -> None:
    rows = staff(["Giorno", "Nome e cognome", "Gruppo di lavoro", "Ore previste", "Ore"])
    broken = ScenarioProvider(Scenario.MALFORMED)

    inspection = understand_with(broken, DataSourceDomain.LABOR, xlsx(rows), date_order="DMY")

    assert inspection.understanding is not None
    assert MAX_CALLS == 2 and 1 <= broken.calls <= MAX_CALLS


def test_the_file_name_never_goes_out() -> None:
    model = Recorder()
    rows = staff(["Giorno", "Nome e cognome", "Gruppo di lavoro", "Ore previste", "Ore"])

    understand_with(
        model,
        DataSourceDomain.LABOR,
        xlsx(rows),
        filename="turni-marta.conti@hotel.example-IBAN-IT60X0542811101000000123456.xlsx",
        date_order="DMY",
    )

    assert model.requests
    for request in model.requests:
        text = request.evidence_json + request.system_instructions
        assert "marta" not in text.lower() and "hotel.example" not in text and ".xlsx" not in text


def test_the_report_tells_what_was_sent_and_what_it_weighed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = Recorder()
    rows = staff(["Giorno", "Nome e cognome", "Gruppo di lavoro", "Ore previste", "Ore"])
    results: list[AiResolution] = []
    real = ImportUnderstandingResolver.resolve

    def spy(
        self: ImportUnderstandingResolver,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        guard: EgressGuard | None = None,
    ) -> AiResolution:
        result = real(self, evidence, fit_of, guard)
        results.append(result)
        return result

    monkeypatch.setattr(ImportUnderstandingResolver, "resolve", spy)

    understand_with(model, DataSourceDomain.LABOR, xlsx(rows), date_order="DMY")

    (result,) = results
    assert result.calls == 1 and result.reason == ResolutionReason.OK
    assert result.payload_chars == len(model.requests[0].evidence_json)
    assert result.input_tokens > 0 and result.output_tokens > 0 and result.response_chars > 0
    assert result.reduced is False


def test_every_resolution_leaves_an_audit_line_of_counts_and_never_of_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dirty = _evidence(
        columns=(
            ColumnEvidence(0, "Mario Rossi", "TEXT", 5, 5, samples=("mario.rossi@example.com",)),
            ColumnEvidence(1, "Gruppo", "TEXT", 5, 3, samples=("Reception",)),
        )
    )

    with caplog.at_level(logging.INFO, logger="app.modules.ai.import_understanding.resolver"):
        ImportUnderstandingResolver(Recorder()).resolve(dirty, _fit)

    (line,) = [r.getMessage() for r in caplog.records if "resolution" in r.getMessage()]
    assert "reason=OK" in line and "calls=1" in line and "payload_chars=" in line
    assert "redactions=2" in line and "prompt=import-understanding-v1" in line
    for content in ("Mario", "Rossi", "mario.rossi", "Reception", "Gruppo"):
        assert content not in line


# --- 5. with no provider nothing can leave


def test_with_no_provider_the_resolver_prepares_reads_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the resolver touched the evidence with no provider configured")

    for name in ("prepare", "fit_budget", "verify"):
        monkeypatch.setattr(egress, name, boom)
        monkeypatch.setattr(resolver_module, name, boom)

    result = ImportUnderstandingResolver(None).resolve(_evidence(), _fit)

    assert result.reason == ResolutionReason.OFF and result.calls == 0
    assert not ImportUnderstandingResolver(None).enabled


def test_with_no_provider_a_whole_file_makes_no_network_call_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def refuse(name: str) -> Callable[..., object]:
        def inner(*_args: object, **_kwargs: object) -> object:
            attempts.append(name)
            raise AssertionError(f"network use: {name}")

        return inner

    monkeypatch.setattr(socket.socket, "connect", refuse("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("connect_ex"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    rows = staff(["Giorno", "Nome e cognome", "Gruppo di lavoro", "Ore previste", "Ore"])
    start = datetime(2026, 11, 14)
    bookings = xlsx(
        [["Codice", "Arrivo", "Partenza", "Colonna 4"]]
        + [[f"R{i}", start + timedelta(i), start + timedelta(i + 2), f"v{i}"] for i in range(8)]
    )

    for domain, content in (
        (DataSourceDomain.LABOR, xlsx(rows)),
        (DataSourceDomain.BOOKINGS, bookings),
    ):
        inspection = understand_with(None, domain, content, date_order="DMY")
        assert inspection.understanding is not None

    assert attempts == []
