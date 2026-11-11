"""Files shaped like a real hotel's export, against a truth written before running them.

`tests/benchmarks/aurora_like` holds the corpus and its reason. What is pinned here is the rule the
pilot depends on: a word in the status column decides what is on the books, so NINFA never decides
it alone, and a column that only says something about the exporter's bookkeeping asks nothing.
"""

import pytest

from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from tests.benchmarks.aurora_like.corpus import PERSONAL_VALUES, Case, build_corpus
from tests.benchmarks.smart_import_v3.observe import make_service, run

CORPUS = build_corpus()


@pytest.fixture(scope="module")
def service() -> UnderstandingService:
    return make_service()


def _ids(cases: list[Case]) -> list[str]:
    return [case.id for case in cases]


ASKS = [case for case in CORPUS if case.outcome == "asks"]
READS = [case for case in CORPUS if case.outcome == "reads"]


@pytest.mark.parametrize("case", ASKS, ids=_ids(ASKS))
def test_a_status_word_nobody_knows_is_asked_about_never_decided(
    service: UnderstandingService, case: Case
) -> None:
    observed = run(service, "bookings", case.filename, case.content)

    assert observed.level == "ASK"
    assert observed.question_kinds == ["VALUE_LABELS"]  # one question, and nothing else
    [question] = observed.questions
    assert question.field == "status"
    assert set(question.labels) == set(case.asked_words)


@pytest.mark.parametrize("case", READS, ids=_ids(READS))
def test_a_file_with_nothing_to_decide_asks_nothing(
    service: UnderstandingService, case: Case
) -> None:
    observed = run(service, "bookings", case.filename, case.content)

    assert observed.level == "READY"
    assert observed.question_kinds == []


@pytest.mark.parametrize(
    "case", [case for case in CORPUS if case.extra_column], ids=lambda case: case.id
)
def test_nothing_is_claimed_from_a_column_about_the_exporter_s_bookkeeping(
    service: UnderstandingService, case: Case
) -> None:
    observed = run(service, "bookings", case.filename, case.content)

    assert [c.field for c in observed.claims if c.header == case.extra_column] == []
    # the booking date stays the booking's, however close a date of the exporter sits
    assert {c.header for c in observed.claims if c.field == "booked_at"} == {"Data prenotazione"}


@pytest.mark.parametrize("case", CORPUS, ids=_ids(CORPUS))
def test_nothing_about_a_person_reaches_the_page(service: UnderstandingService, case: Case) -> None:
    observed = run(service, "bookings", case.filename, case.content)

    assert not [value for value in PERSONAL_VALUES if value in observed.payload]


def test_the_answer_settles_the_file(service: UnderstandingService) -> None:
    case = next(case for case in ASKS if case.id == "word_modificata")

    observed = run(
        service,
        "bookings",
        case.filename,
        case.content,
        answers=UnderstandAnswers(labels={"status_mapping": {"Modificata": "CONFIRMED"}}),
    )

    assert observed.level == "READY"
    assert observed.question_kinds == []
    assert observed.labels["status_mapping"]["Modificata"] == "CONFIRMED"
