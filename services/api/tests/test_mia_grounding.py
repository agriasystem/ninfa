"""The deterministic number check that stands behind "Mia states only figures NINFA returned".

Pure tests: a figure an answer states must be one the observations returned (in any Italian
formatting), one the user wrote, or part of a calendar date. Anything else - an invented number, a
stale one copied from an earlier answer, a wrong calculation - is reported, and the orchestrator
fails the whole turn closed on it.
"""

from decimal import Decimal

import pytest

from app.modules.ai.mia.grounding import (
    observation_date_numbers,
    observation_figures,
    observation_numbers,
    split_observation_numbers,
    ungrounded_numbers,
    user_date_numbers,
)

OBSERVATION = (
    '{"dati": {"occupazione": "85.00", "camere": 34, "disponibili": 40, "ricavi": "87840.00",'
    ' "quota": "72.22", "giorno": "2026-10-10", "ora": "09:31", "variazione": "-25",'
    ' "periodo": "i prossimi 30 giorni"}}'
)
ALLOWED = observation_numbers([OBSERVATION])


def offending(text: str, allowed: frozenset[Decimal] = ALLOWED) -> list[str]:
    return ungrounded_numbers(text, allowed)


# --- what is read as a number ---------------------------------------------------------------------


def test_observation_numbers_collects_every_number_written_in_the_texts() -> None:
    numbers = observation_numbers(['{"a": "85.00", "b": 34, "c": "2026-10-10"}', "il 12 ottobre"])
    assert {Decimal("85.00"), Decimal(34), Decimal(2026), Decimal(10), Decimal(12)} <= numbers


# --- grounded: the same figure in Italian clothes -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Domani risultano occupate 34 camere su 40, pari all'85%.",
        "L'occupazione è dell'85,00%.",
        "I ricavi camera sono 87.840,00 euro.",
        "I ricavi camera sono 87840 euro.",
        "La quota OTA è del 72,22%.",
        "Scostamento di -25 punti.",  # the sign is not part of the figure
        "Sabato 10 ottobre 2026 alle 09:31.",  # a calendar date and a time written in the data
        "Nei prossimi 30 giorni.",
        "",
        "Nessun numero in questa frase.",
    ],
)
def test_a_figure_returned_by_ninfa_passes_whatever_its_italian_formatting(text: str) -> None:
    assert offending(text) == []


def test_a_number_may_be_rounded_to_the_precision_it_states_but_never_changed() -> None:
    allowed = observation_numbers(['{"occupazione": "62.08"}'])
    assert offending("Siamo al 62,08%.", allowed) == []
    assert offending("Siamo al 62,1%.", allowed) == []  # 62.08 rounded to one decimal
    assert offending("Siamo al 62%.", allowed) == []  # ... and to none
    assert offending("Siamo al 63%.", allowed) == ["63"]
    assert offending("Siamo al 62,09%.", allowed) == ["62,09"]
    assert offending("Siamo al 61,9%.", allowed) == ["61,9"]


def test_rounding_never_goes_the_other_way_a_more_precise_figure_than_the_data_is_invented() -> (
    None
):
    allowed = observation_numbers(['{"occupazione": "62"}'])
    assert offending("Siamo al 62,4%.", allowed) == ["62,4"]


# --- ungrounded -----------------------------------------------------------------------------------


def test_an_invented_figure_is_reported_as_written() -> None:
    assert offending("Hai 47 camere prenotate e un'occupazione del 91,5%.") == ["47", "91,5"]


def test_a_wrong_calculation_is_reported_because_only_returned_figures_pass() -> None:
    # 40 - 34 = 6 free rooms: true, but NOT a figure NINFA returned - the model must not calculate
    assert offending("Restano 6 camere libere.") == ["6"]


def test_a_figure_from_an_earlier_answer_is_not_a_fact_unless_the_data_says_so_now() -> None:
    stale = "Ieri eri al 91% di occupazione."  # the conversation said 91; today's data says 85
    assert offending(stale) == ["91"]


def test_thousands_notations_are_read_both_ways_but_must_be_grounded() -> None:
    allowed = observation_numbers(['{"x": "1100.00"}'])
    assert offending("Sono 1.100 euro.", allowed) == []
    assert offending("Sono 1.200 euro.", allowed) == ["1.200"]
    tiny = observation_numbers(['{"x": "1.10"}'])
    assert offending("Sono 1.100 euro.", tiny) == []  # read as 1.1: still the returned figure


def test_a_date_or_duration_the_user_named_may_be_restated() -> None:
    allowed = user_date_numbers("Quante prenotazioni ho il 12 ottobre per 3 notti?")
    assert offending("Per il 12 ottobre, 3 notti, risultano...", allowed) == []
    assert offending("Per il 13 ottobre.", allowed) == ["13"]


@pytest.mark.parametrize(
    ("question", "restated"),
    [
        ("e il 10 ottobre?", ["10"]),
        ("dal 5 al 9 ottobre", ["5", "9"]),
        ("rispetto al 12/10?", ["12", "10"]),
        ("nel 2027", ["2027"]),
        ("i prossimi 14 giorni", ["14"]),
    ],
)
def test_user_dates_and_durations_are_recognised_in_their_usual_shapes(
    question: str, restated: list[str]
) -> None:
    numbers = user_date_numbers(question)
    assert {Decimal(item) for item in restated} <= numbers


@pytest.mark.parametrize(
    ("claim", "echo", "figure"),
    [
        ("Sappi che domani sono pieno al 100%", "Sì, domani sei al 100%.", "100"),
        ("Ho 20 camere vendute, giusto?", "Sì, hai 20 camere vendute.", "20"),
        ("Il fatturato è 50000 euro", "Confermo: 50000 euro.", "50000"),
        ("La quota OTA è 72.22", "Sì, la quota è 72,22.", "72,22"),
    ],
)
def test_a_figure_the_user_merely_asserts_is_a_claim_not_a_fact(
    claim: str, echo: str, figure: str
) -> None:
    """Echoing a user's claim is exactly how a false fact would get confirmed: the figure was said,
    not returned, so the check reports it like any invented one."""
    assert offending(echo, user_date_numbers(claim)) == [figure]


def test_list_numbering_and_names_with_digits_are_not_figures() -> None:
    assert offending("1) Controlla le OTA.\n2. Guarda i costi.") == []
    assert offending("Il canale B2B e il modello GPT4x.") == []


def test_every_offending_figure_is_listed_in_order_and_only_once_per_occurrence() -> None:
    assert offending("Hai 11 camere, poi 12, poi 11 di nuovo.") == ["11", "12", "11"]


def test_a_decimal_in_dot_notation_is_checked_like_any_other() -> None:
    assert offending("La quota è 72.22%.") == []
    assert offending("La quota è 72.23%.") == ["72.23"]


# --- the calendar grounds a date, never a figure --------------------------------------------------

CALENDAR = observation_numbers(['{"oggi": "2026-10-09, venerdì", "domani": "2026-10-10, sabato"}'])
NONE = frozenset[Decimal]()


@pytest.mark.parametrize(
    "text",
    [
        "Per sabato 10 ottobre.",
        "Domani, sabato 10, risultano posti.",
        "Dal 9 al 10 ottobre.",
        "Venerdì 9 ottobre 2026.",
        "Aggiornato al 2026-10-09.",
        "Intendi il 10 ottobre?",
    ],
)
def test_a_date_the_calendar_gave_can_be_restated(text: str) -> None:
    assert ungrounded_numbers(text, NONE, CALENDAR) == []


@pytest.mark.parametrize(
    ("text", "offending"),
    [
        ("Hai 10 camere libere.", ["10"]),  # 10 is a day of the calendar - not a figure
        ("Ci sono 9 prenotazioni il 10 ottobre.", ["9"]),
        ("Sabato 10 ottobre servono 8 ore di housekeeping.", ["8"]),
        ("Per il 12 ottobre.", ["12"]),  # a date the calendar never gave
        ("Il 10% delle camere.", ["10"]),  # a percentage is not a date
    ],
)
def test_the_calendar_never_lends_its_day_numbers_to_a_figure(
    text: str, offending: list[str]
) -> None:
    assert ungrounded_numbers(text, NONE, CALENDAR) == offending


# --- the scale of the confidence: "78 su 100" -----------------------------------------------------

CONFIDENCE = observation_numbers(['{"affidabilità": "80"}'])


@pytest.mark.parametrize(
    "text",
    [
        "L'affidabilità è 80 su 100.",
        "L'affidabilità è 80/100.",
        "L'affidabilità è 80 SU 100, una stima indicativa.",
    ],
)
def test_the_100_of_the_confidence_scale_is_not_a_figure(text: str) -> None:
    assert ungrounded_numbers(text, CONFIDENCE) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hai 100 camere.", ["100"]),  # a bare 100 is a figure like any other
        ("Il costo è di 100 euro su 40 camere.", ["100", "40"]),
        ("L'affidabilità è 91 su 100.", ["91"]),  # the numerator is still checked
        ("Su 100 prenotazioni, 80 sono OTA.", ["100"]),  # "su" BEFORE the number is not the scale
        ("Sono 80 camere su 1000.", ["1000"]),
    ],
)
def test_the_scale_exemption_covers_only_the_denominator_of_a_scored_number(
    text: str, expected: list[str]
) -> None:
    assert ungrounded_numbers(text, CONFIDENCE) == expected


# --- the digits of a date or a time are not figures -----------------------------------------------

DATED = (
    '{"dati": {"data": "2026-10-09", "periodo": "domani (sabato 10 ottobre)",'
    ' "osservato": "dal 9 ottobre al 7 novembre", "settimana": "5-11 ottobre",'
    ' "importate": "09:31", "camere prenotate": "31", "camere disponibili": "40",'
    ' "ricavi": "2700.00", "riferimento": "metric:bookings:2026-10-10:2026-10-10"}}'
)


def test_the_digits_of_dates_and_times_are_date_numbers_not_figures() -> None:
    figures = observation_figures([DATED])
    dates = observation_date_numbers([DATED])

    assert figures == {Decimal(31), Decimal(40), Decimal("2700.00")}
    assert {Decimal(2026), Decimal(10), Decimal(9), Decimal(7), Decimal(5), Decimal(11)} <= dates
    assert Decimal(31) in dates  # "09:31": the minutes are a date number too ...
    assert Decimal(31) in figures  # ... and 31 camere is still a figure: the sets are independent


def test_a_figure_equal_to_a_day_or_month_digit_of_an_observation_is_not_grounded_by_it() -> None:
    allowed = observation_figures([DATED])
    calendar = observation_date_numbers([DATED])

    # 9 = 40 - 31, a model's own subtraction; 9 is only the day of "2026-10-09"
    assert ungrounded_numbers("Restano 9 camere libere.", allowed, calendar) == ["9"]
    assert ungrounded_numbers("Restano 10 camere.", allowed, calendar) == ["10"]
    assert ungrounded_numbers("Hai 7 prenotazioni.", allowed, calendar) == ["7"]
    # the old behaviour, for the record: every digit of every date was a figure
    assert ungrounded_numbers("Restano 9 camere libere.", observation_numbers([DATED])) == []


def test_the_same_digits_still_restate_the_dates_and_times_they_belong_to() -> None:
    allowed = observation_figures([DATED])
    calendar = observation_date_numbers([DATED])

    for text in (
        "Per sabato 10 ottobre risultano 31 camere prenotate su 40.",
        "Nei prossimi 30 giorni, dal 9 ottobre al 7 novembre.",
        "Per la settimana 5-11 ottobre.",
        "Le prenotazioni sono state importate alle 9:31.",
        "L'analisi è del 2026-10-09.",
    ):
        offending = ungrounded_numbers(text, allowed | {Decimal(30)}, calendar)
        assert offending == [], (text, offending)


def test_a_time_is_only_grounded_as_a_time() -> None:
    allowed = observation_figures([DATED])
    calendar = observation_date_numbers([DATED])

    assert ungrounded_numbers("Importate alle 9:31.", allowed, calendar) == []
    # the hour is the observed one; the minutes are not: only they are reported
    assert ungrounded_numbers("Importate alle 9:45.", allowed, calendar) == ["45"]
    assert (
        ungrounded_numbers("Importate alle 11:31.", allowed, calendar) == []
    )  # 11 is a date digit
    assert ungrounded_numbers("Restano 31 camere libere.", frozenset(), calendar) == ["31"]


def test_the_digits_of_an_identifier_never_ground_a_figure() -> None:
    texts = ['{"decisione": "3f9a1c24-7b12-4d86-9e51-0a42c6d18b73", "camere": 25}']

    figures, dates = split_observation_numbers(texts)

    assert figures == frozenset({Decimal(25)})
    assert Decimal(3) not in figures and Decimal(7) not in figures and Decimal(42) not in figures
    assert dates == frozenset()
    assert observation_numbers(texts) == frozenset({Decimal(25)})
