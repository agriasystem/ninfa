"""Smart Import V4: NINFA's domain rules applied to a READING before it can be called certain.

The importers already refuse a bad row. This is the first line: a column named for a field whose
values break that field's own rule is probably not that field, and the person is asked now.
It only ever takes certainty away.
"""

from datetime import date
from typing import Any

from app.modules.data_sources.algorithmic.engine import DEFAULT, AlgorithmicEngine
from app.modules.data_sources.algorithmic.validate import validate_reading
from app.modules.data_sources.proposal import Proposal, propose
from app.modules.data_sources.semantics import Level
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.ingestion.models import DataSourceDomain
from tests.algorithmic_support import CHANNELS, MONEY, ROOMS, STATUSES, codes, stay, table

B = DataSourceDomain.BOOKINGS
booked, arrival, departure = stay()


def named() -> dict[str, list[Any]]:
    return {
        "Reservation Code": list(codes()),
        "Booking Date": list(booked),
        "Check in": list(arrival),
        "Check out": list(departure),
        "Status": list(STATUSES),
        "Rooms": list(ROOMS),
        "Room Revenue": list(MONEY),
        "Channel": list(CHANNELS),
    }


def read(columns: dict[str, list[Any]]) -> Proposal:
    return propose(BOOKINGS, table(columns), engine=AlgorithmicEngine(DEFAULT))


def test_a_clean_file_has_nothing_to_report() -> None:
    samples = table(named())
    chosen = {2: "check_in", 3: "check_out", 5: "rooms", 6: "room_revenue"}

    assert validate_reading(B, chosen, samples) == []


def test_arrival_and_departure_on_each_others_columns_are_caught() -> None:
    swapped = named()
    swapped["Check in"], swapped["Check out"] = list(departure), list(arrival)

    proposal = read(swapped)

    levels = {c.field: c.level for c in proposal.columns if c.field}
    assert levels["check_in"] == Level.LOW
    assert levels["check_out"] == Level.LOW
    findings = validate_reading(B, {2: "check_in", 3: "check_out"}, table(swapped))
    assert {f.field for f in findings} == {"check_in", "check_out"}
    assert "swapped" in findings[0].reason


def test_a_few_bad_rows_are_the_importers_to_report_not_a_swap() -> None:
    mostly = named()
    out = list(departure)
    out[3] = date(2026, 1, 1)  # one departure before its arrival
    mostly["Check out"] = out

    assert validate_reading(B, {2: "check_in", 3: "check_out"}, table(mostly)) == []


def test_a_room_count_of_zero_or_with_decimals_is_asked_about() -> None:
    for bad in ([0, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1], [1, 1, 1.5, 1, 1, 1, 1, 1, 1, 1, 1, 1]):
        columns = named()
        columns["Rooms"] = bad

        findings = validate_reading(B, {5: "rooms"}, table(columns))

        assert [f.field for f in findings] == ["rooms"]
        assert findings[0].level == Level.MEDIUM


def test_a_negative_booking_amount_is_a_credit_not_a_room_revenue() -> None:
    columns = named()
    columns["Room Revenue"] = [-50.0, *MONEY[1:]]

    findings = validate_reading(B, {6: "room_revenue"}, table(columns))

    assert [f.field for f in findings] == ["room_revenue"]


def test_validation_never_adds_certainty() -> None:
    columns = named()
    columns["Rooms"] = [0, *ROOMS[1:]]

    proposal = read(columns)

    rooms = next(c for c in proposal.columns if c.field == "rooms")
    assert rooms.level != Level.HIGH
    assert any("whole number" in line for line in rooms.evidence)
