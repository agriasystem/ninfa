"""A column nobody read that moves with one somebody did is never lost in silence.

Hours planned and hours worked, what a room cost and what the whole stay cost: an import can run
with one of them, so a file that reads one and holds an unread column moving with it used to be
READY with the other quietly left out. The rule is about the VALUES (never the header the rules
could not read) and about NO provider: it must hold with the model off, with the semantic layer in
any mode against any stand-in, and with the original assistant.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode
from app.modules.data_sources.mapping_types import FileInspection
from app.modules.data_sources.understanding_siblings import moves_with
from app.modules.ingestion.models import DataSourceDomain
from tests.booking_support import xlsx_bytes
from tests.import_ai_support import Scenario, ScenarioProvider, understand_with
from tests.semantic_support import Behaviour, SemanticStandIn, outline, understand_semantic

LABOR = DataSourceDomain.LABOR
BOOKINGS = DataSourceDomain.BOOKINGS
PLANNED = (7, 7.5, 8, 7, 6, 8, 7.5, 7)
WORKED = (7.5, 7, 8.5, 7, 6.5, 8, 7, 8)


def staff(extra_header: str, extra: tuple[Any, ...], planned_header: str = "Ore previste") -> bytes:
    rows = [
        [datetime(2026, 11, 2 + i), ("Reception", "Cucina")[i % 2], PLANNED[i], extra[i]]
        for i in range(len(PLANNED))
    ]
    return xlsx_bytes({"Turni": [["Giorno", "Reparto", planned_header, extra_header], *rows]})


def stays(
    extra_header: str, extra: tuple[Any, ...], revenue_header: str = "Importo totale"
) -> bytes:
    body = []
    for i in range(len(extra)):
        arrival = datetime(2026, 11, 2 + i)
        body.append(
            [
                f"R-{100 + i}",
                datetime(2026, 10, 1 + i),
                arrival,
                arrival + timedelta(days=2),
                "Confermata",
                1,
                (200, 150, 230, 180, 210, 170, 260, 190)[i],
                ("Booking.com", "Expedia", "Diretto", "Airbnb")[i % 4],
                extra[i],
            ]
        )
    header = [
        "Codice prenotazione",
        "Data prenotazione",
        "Arrivo",
        "Partenza",
        "Stato",
        "Camere",
        revenue_header,
        "Canale",
        extra_header,
    ]
    return xlsx_bytes({"Prenotazioni": [header, *body]})


def read(content: bytes, domain: DataSourceDomain, **answers: Any) -> dict[str, Any]:
    return outline(understand_semantic(None, domain, content, **answers))


# --- the rule itself -----------------------------------------------------------------------------


def test_unread_hours_that_move_with_the_planned_ones_are_asked_about_not_left_out() -> None:
    result = read(staff("Impegno reale", WORKED), LABOR)

    assert result["level"] == "ASK"
    assert [q[0] for q in result["questions"]] == ["CONFIRM:Impegno reale"]
    assert ("Impegno reale", None, None) in result["columns"]


def test_the_question_says_what_the_column_would_be_and_it_is_answered_like_any_other() -> None:
    inspection = understand_semantic(None, LABOR, staff("Impegno reale", WORKED))
    info = inspection.understanding
    assert info is not None
    (question,) = info.questions
    assert (question.field, question.candidate) == ("actual_hours", "actual_hours")

    answered = read(
        staff("Impegno reale", WORKED), LABOR, column_fields={"Impegno reale": "actual_hours"}
    )

    assert answered["level"] == "READY" and answered["questions"] == []


def test_the_other_way_round_is_the_same() -> None:
    # the actual hours are read by name, the planned ones are not
    rows = [
        [datetime(2026, 11, 2 + i), ("Reception", "Cucina")[i % 2], WORKED[i], PLANNED[i]]
        for i in range(8)
    ]
    content = xlsx_bytes(
        {"Turni": [["Giorno", "Reparto", "Ore effettive", "Impegno previsto"], *rows]}
    )

    result = read(content, LABOR)

    assert result["level"] == "ASK"
    assert [q[0] for q in result["questions"]] == ["CONFIRM:Impegno previsto"]


def test_hours_written_with_a_unit_are_numbers_too() -> None:
    content = staff("Impegno reale", tuple(f"{h} ore" for h in WORKED))

    assert read(content, LABOR)["level"] == "ASK"


def test_an_unread_column_that_does_not_move_with_the_hours_is_left_alone() -> None:
    for header, values in (
        ("Pausa", (30, 30, 45, 30, 30, 45, 30, 30)),  # minutes of a break
        ("Straordinari", (0.5, 0, 1, 0, 0.5, 0, 0, 1)),  # a small, other thing
        ("Postazione n.", (12, 14, 11, 15, 16, 18, 22, 25)),  # a number that is nothing like hours
    ):
        result = read(staff(header, values), LABOR)

        assert result["level"] == "READY", header
        assert result["questions"] == [], header


def test_hours_whose_name_says_they_are_another_kind_are_never_the_other_half() -> None:
    # the numbers move with the planned hours (as the hours worked would), but the header SAYS they
    # are contract hours, overtime or a holiday: another thing, left alone - the name only ever
    # rules a column out, never in
    for header in ("Ore da contratto", "Ore straordinario", "Ore ferie"):
        result = read(staff(header, WORKED), LABOR)

        assert result["level"] == "READY", header
        assert result["questions"] == [], header
    # the same numbers under a header nobody knows are still asked about
    assert read(staff("Impegno reale", WORKED), LABOR)["level"] == "ASK"


def test_an_unread_amount_equal_to_the_read_one_row_after_row_asks_nothing() -> None:
    # nothing the import lacks is lost: the numbers are the same (a room number that happens to
    # run beside the amounts, a total with no extras)
    room = (200, 150, 230, 180, 210, 170, 260, 190)
    same = tuple(round(value * 1.004, 2) for value in room)

    result = read(stays("Totale incassato", same, revenue_header="Ricavo camera"), BOOKINGS)

    assert result["level"] == "READY"
    assert result["questions"] == []


def test_a_column_of_words_is_never_a_sibling() -> None:
    result = read(staff("Annotazione turno", ("ok",) * 8), LABOR)

    assert result["level"] == "READY"


def test_unread_money_that_moves_with_the_revenue_goes_to_the_matching_screen() -> None:
    # the whole stay is read, the room's own revenue is called something nobody knows
    result = read(stays("Incasso", (180, 135, 207, 162, 189, 153, 234, 171)), BOOKINGS)

    assert result["level"] == "MANUAL"
    assert result["questions"] == []  # money is never a yes or no


def test_a_commission_a_count_or_a_per_night_price_is_not_asked_about() -> None:
    for header, values in (
        ("Commissione", (30, 22, 35, 27, 31, 25, 39, 28)),  # 15%: nowhere near
        ("Notti", (2,) * 8),
        ("Prezzo a notte", (100, 75, 115, 90, 105, 85, 130, 95)),  # half of a two-night stay
    ):
        result = read(stays(header, values, revenue_header="Ricavo camera"), BOOKINGS)

        assert result["level"] == "READY", header


def test_a_file_that_reads_both_halves_is_untouched() -> None:
    rows = [
        [datetime(2026, 11, 2 + i), ("Reception", "Cucina")[i % 2], PLANNED[i], WORKED[i]]
        for i in range(8)
    ]
    content = xlsx_bytes({"Turni": [["Giorno", "Reparto", "Ore previste", "Ore effettive"], *rows]})

    assert read(content, LABOR)["level"] == "READY"


def test_too_few_rows_prove_nothing() -> None:
    rows = [[datetime(2026, 11, 2), "Reception", 7, 7.5], [datetime(2026, 11, 3), "Cucina", 8, 8]]
    content = xlsx_bytes({"Turni": [["Giorno", "Reparto", "Ore previste", "Impegno reale"], *rows]})

    # (with so few rows the rules are unsure of every column; what matters is that the unread one
    # is not taken for a sibling on two rows)
    result = read(content, LABOR)
    assert "CONFIRM:Impegno reale" not in [q[0] for q in result["questions"]]


def test_moves_with_needs_the_values_to_stay_in_proportion_row_after_row() -> None:
    from app.modules.data_sources.column_profile import ColumnSample

    def sample(position: int, values: tuple[Any, ...]) -> ColumnSample:
        return ColumnSample(
            position, "x", tuple(str(v) for v in values), tuple(values), tuple(values)
        )

    base = sample(0, (7, 7.5, 8, 7, 6))
    assert moves_with(sample(1, (7.5, 7, 8.5, 7, 6.5)), base)
    assert not moves_with(sample(1, (1, 2, 3, 4, 5)), base)
    assert not moves_with(sample(1, (70, 75, 80, 70, 60)), base)  # ten times: another unit
    assert not moves_with(ColumnSample(1, "x", (), (), ()), base)  # nothing to compare


# --- no provider is part of it -------------------------------------------------------------------

STANDINS = [
    Behaviour.ORACLE,
    Behaviour.WRONG,
    Behaviour.OBEYS_INJECTION,
    Behaviour.UNKNOWN,
    Behaviour.LOW,
    Behaviour.TIMEOUT,
    Behaviour.GARBAGE,
]


@pytest.mark.parametrize("mode", [AiMode.OFF, AiMode.SHADOW, AiMode.ASSIST])
@pytest.mark.parametrize("behaviour", STANDINS)
def test_no_model_in_any_mode_makes_a_file_with_an_unread_sibling_ready(
    mode: AiMode, behaviour: Behaviour
) -> None:
    content = staff("Impegno reale", WORKED)
    provider = SemanticStandIn(behaviour, {"Impegno reale": "actual_hours"})

    result = outline(understand_semantic(provider, LABOR, content, mode=mode))

    assert result["level"] != "READY"


@pytest.mark.parametrize(
    "scenario", [Scenario.AGREE, Scenario.WRONG, Scenario.SURE_AND_WRONG, Scenario.OBEYS_INJECTION]
)
def test_the_original_assistant_cannot_make_it_ready_either(scenario: Scenario) -> None:
    provider = ScenarioProvider(scenario, {"Impegno reale": "actual_hours"})

    inspection: FileInspection = understand_with(provider, LABOR, staff("Impegno reale", WORKED))

    assert inspection.understanding is not None
    assert inspection.understanding.level.value != "READY"


def test_the_rule_does_not_depend_on_there_being_a_resolver_at_all() -> None:
    from tests.semantic_support import semantic_service

    service = semantic_service(None)
    assert (
        isinstance(service._resolver, ImportUnderstandingResolver) and not service._resolver.enabled
    )
    result = read(staff("Impegno reale", WORKED), LABOR)

    assert result["level"] == "ASK"


def test_a_model_that_reads_the_column_right_still_leaves_a_question_for_hours() -> None:
    provider = SemanticStandIn(Behaviour.ORACLE, {"Impegno reale": "actual_hours"})

    result = outline(understand_semantic(provider, LABOR, staff("Impegno reale", WORKED)))

    # hours are never certified by a model's word: the person still says yes
    assert result["level"] == "ASK"
    assert [q[0] for q in result["questions"]] == ["CONFIRM:Impegno reale"]


def test_a_whole_is_never_smaller_than_its_part_so_a_net_after_commission_is_not_a_stay_total() -> (
    None
):
    # the room's revenue is read; "Netto dopo commissione" is about 87% of it: it can be nothing
    # that contains the room, so it is not asked about and the file stays READY
    room = (200, 150, 230, 180, 210, 170, 260, 190)
    net = tuple(round(value * 0.87, 2) for value in room)

    result = read(stays("Netto dopo commissione", net, revenue_header="Ricavo camera"), BOOKINGS)

    assert result["level"] == "READY"


def test_a_column_larger_than_the_room_may_be_the_stay_total_so_money_goes_to_matching() -> None:
    # the room's revenue is read by its name ("Ricavo camera"): an unread column a little LARGER
    # than it, row after row, could be the whole stay - and money is never put as a yes or no
    larger = (240, 180, 276, 216, 252, 204, 312, 228)
    result = read(stays("Volume d affari", larger, revenue_header="Ricavo camera"), BOOKINGS)

    assert result["level"] == "MANUAL"


def test_a_read_name_that_is_also_a_stay_total_name_leaves_a_smaller_column_in_doubt() -> None:
    # "Totale soggiorno" is read as the room's revenue, but it is as much a stay total: NINFA does
    # not know which half it holds, so a column a little SMALLER ("Incasso") may be the room's
    # revenue - the file is not READY with it silently left out
    smaller = (180, 135, 207, 162, 189, 153, 234, 171)
    result = read(stays("Incasso", smaller, revenue_header="Totale soggiorno"), BOOKINGS)

    assert result["level"] == "MANUAL"
