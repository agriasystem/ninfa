"""PB-2: the last read of what is about to be sent looks at ONE STRING AT A TIME.

The egress gate reads the final document once more before a call. It used to read the whole JSON as
one text, so two innocent neighbours in a list - the sample "@cmd" (a formula-injection attempt in a
cell) and the sample "fdp.exe" - became "an e-mail address" through the punctuation of the JSON
between them, and the call was blocked (fail closed, nothing left the server, but a file the model
could have helped with was left to the person). Found on the adversarial document
B62_adv_formulas_and_html_in_cells.

Now every string of the decoded payload - keys and values, at any depth - is read on its own: a real
address, number, tax code or IBAN in ONE string still blocks, hidden or not; strings next to each
other are never combined.

No database, no network, no model.
"""

import json
from typing import Any

import pytest

from app.modules.ai.import_understanding.egress import (
    EgressGuard,
    EgressViolationError,
    prepare,
    verify,
)
from app.modules.ai.import_understanding.prompt import evidence_json
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import (
    ColumnEvidence,
    ResolutionReason,
    UnderstandingEvidence,
)
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.redaction import PersonalDataGuard
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.ai_readiness import variants
from tests.benchmarks.smart_import_v3.corpus import build_corpus
from tests.import_ai_support import Recorder, understand_with

# the samples of the "Commento" column of the adversarial document, exactly as they were sent
B62_SAMPLES = [
    '=HYPERLINK("http://example.invalid","x")',
    "=1+1",
    "<img src=x onerror=alert(1)>",
    "@cmd",
    "-2+3",
    "fdp.exe",
]
ZWSP = "​"

REAL = {
    "email": "mario.rossi@example.com",
    "phone": "+39 333 1234567",
    "tax code": "RSSMRA85T10A562S",
    "iban": "IT60X0542811101000000123456",
}
DISGUISED = {
    "email with a zero-width space": f"mario.ro{ZWSP}ssi@example.com",
    "tax code with a Cyrillic letter": "RSSМRA85T10A562S",
    "iban with a soft hyphen": "IT60X0542811101­000000123456",
    "phone with a BOM": "+39 333﻿1234567",
}


def _document(**sections: Any) -> str:
    # compact, as the evidence is really serialised (`prompt.evidence_json`)
    return json.dumps(
        {"columns": [], "sheets": [], "questions": [], **sections},
        ensure_ascii=False,
        separators=(",", ":"),
    )


# --- a real personal value in ONE string still blocks, wherever it sits ---


@pytest.mark.parametrize("kind", list(REAL))
@pytest.mark.parametrize(
    "place",
    ["value", "list item", "nested", "key", "second item of several"],
)
def test_a_real_personal_value_in_one_string_blocks_wherever_it_sits(kind: str, place: str) -> None:
    value = REAL[kind]
    places: dict[str, dict[str, Any]] = {
        "value": {"title": value},
        "list item": {"columns": [value]},
        "nested": {"columns": [{"header": "Colonna", "samples": ["Reception", value]}]},
        "key": {"columns": [{value: 1}]},
        "second item of several": {"columns": [{"samples": ["a", "b", f"nota {value}", "d"]}]},
    }
    placed = places[place]

    with pytest.raises(EgressViolationError) as caught:
        verify(_document(**placed), EgressGuard())

    assert caught.value.codes, f"{kind} in {place} was not found"
    assert value not in str(caught.value)  # the codes are words, never the content


@pytest.mark.parametrize("name", list(DISGUISED))
def test_a_disguised_personal_value_in_one_string_still_blocks(name: str) -> None:
    with pytest.raises(EgressViolationError):
        verify(_document(columns=[{"samples": [DISGUISED[name]]}]), EgressGuard())


def test_a_personal_value_of_the_file_in_one_string_still_blocks() -> None:
    guard = EgressGuard(
        scrub=PersonalDataGuard.for_columns([(PiiKind.PERSON_NAME, ["Giulia Ferretti"])]).clean
    )

    with pytest.raises(EgressViolationError) as caught:
        verify(_document(columns=[{"samples": ["Reception", "Giulia Ferretti"]}]), guard)

    assert caught.value.codes == ("FILE_VALUE",)


def test_text_that_is_not_json_is_read_whole_and_still_blocks() -> None:
    with pytest.raises(EgressViolationError):
        verify("contact mario.rossi@example.com about the roster", EgressGuard())


# --- strings next to each other are never combined ---


def test_the_two_neighbours_that_used_to_make_an_address_are_not_one() -> None:
    verify(_document(columns=[{"samples": ["@cmd", "fdp.exe"]}]), EgressGuard())

    # ...whatever surrounds them and whichever way round they sit
    verify(_document(columns=[{"samples": ["fdp.exe", "@cmd"]}]), EgressGuard())
    verify(_document(columns=[{"samples": ["x", "@cmd"]}, {"samples": ["fdp.exe"]}]), EgressGuard())


def test_the_whole_adversarial_payload_of_b62_is_not_an_address() -> None:
    verify(_document(columns=[{"header": "Commento", "samples": B62_SAMPLES}]), EgressGuard())


def test_the_old_whole_document_reading_would_have_blocked_it() -> None:
    # documents WHY the reading is per string: this is what the old gate saw
    from app.modules.ai.import_understanding.sanitize import personal_shapes_in

    document = _document(columns=[{"header": "Commento", "samples": B62_SAMPLES}])

    assert "EMAIL" in personal_shapes_in(document)  # as one text: a false "address"
    verify(document, EgressGuard())  # one string at a time: nothing


# --- through the resolver: the call is made, and nothing personal is in it ---


def _evidence_with_the_b62_column() -> UnderstandingEvidence:
    return UnderstandingEvidence(
        expected_domain="BOOKINGS",
        fields={"BOOKINGS": ("source_record_id", "check_in", "status")},
        columns=(
            ColumnEvidence(0, "Colonna 9", "TEXT", 8, 8),
            ColumnEvidence(1, "Commento", "TEXT", 8, 6, samples=tuple(B62_SAMPLES)),
        ),
    )


def test_a_column_of_hostile_cells_no_longer_blocks_the_call() -> None:
    model = Recorder()

    result = ImportUnderstandingResolver(model).resolve(
        _evidence_with_the_b62_column(), lambda *_: 1.0
    )

    assert result.reason == ResolutionReason.OK and result.calls == 1
    assert len(model.requests) == 1 and model.violations == []
    sent = json.loads(model.requests[0].evidence_json)
    assert sent["columns"][1]["samples"] == B62_SAMPLES  # the cells are data, shown as they are


def test_the_hostile_cells_are_still_cleaned_of_anything_personal() -> None:
    dirty = UnderstandingEvidence(
        expected_domain="BOOKINGS",
        fields={"BOOKINGS": ("source_record_id",)},
        columns=(
            ColumnEvidence(0, "Colonna 9", "TEXT", 8, 8),
            ColumnEvidence(
                1, "Commento", "TEXT", 8, 6, samples=("@cmd", "mario.rossi@example.com", "fdp.exe")
            ),
        ),
    )
    model = Recorder(forbidden=("mario.rossi",))

    ImportUnderstandingResolver(model).resolve(dirty, lambda *_: 1.0)

    assert model.violations == []
    assert evidence_json(prepare(dirty, EgressGuard())[0]).count("[removed]") == 1


def test_the_real_adversarial_document_reaches_the_model_and_nothing_personal_with_it() -> None:
    corpus = build_corpus()
    source = next(d for d in corpus if d.id.startswith("B62_"))
    (hidden,) = variants([source])
    model = Recorder(forbidden=hidden.golden.pii_values)

    understand_with(model, DataSourceDomain.BOOKINGS, hidden.content, filename=hidden.filename)

    assert len(model.requests) == 1, "the call that used to be blocked is made"
    assert model.violations == []
