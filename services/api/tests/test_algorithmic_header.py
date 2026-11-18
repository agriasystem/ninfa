"""Smart Import V4: headers read the way a person reads them, then matched with RapidFuzz.

`BookingStatus`, `booking_status` and `bookingstatus` are one header; a spelling mistake is still
the
header it meant; two headers that differ by a WORD (`check in` / `check out`) are different headers
however many letters they share; and a phrase that means another thing (`ADR`) is never the field it
resembles. The matcher produces evidence, never a mapping.
"""

import pytest

from app.modules.data_sources.algorithmic.header import (
    Kind,
    normalize,
    read_header,
    split_camel,
    vocabulary_words,
)
from app.modules.ingestion.models import DataSourceDomain

B, L, C = DataSourceDomain.BOOKINGS, DataSourceDomain.LABOR, DataSourceDomain.COSTS


def field_of(domain: DataSourceDomain, raw: str) -> str | None:
    matches = read_header(domain, raw).matches
    return max(matches.values(), key=lambda m: m.score).field if matches else None


# --- normalising ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "Booking Status",
        "booking_status",
        "BookingStatus",
        "booking-status",
        "Booking.Status",
        "BOOKING_STATUS",
        "bookingstatus",
        "Booking Status (PMS)",
        "Booking Status *",
        "  booking   status  ",
    ],
)
def test_every_way_of_writing_a_header_normalises_to_the_same_words(raw: str) -> None:
    assert normalize(raw).text == "booking status"


def test_camel_case_is_split_including_acronyms() -> None:
    assert split_camel("CheckInDate") == "Check In Date"
    assert split_camel("PMSId") == "PMS Id"
    assert normalize("OTACommission").words == ("ota", "commission")


def test_the_raw_header_is_never_lost() -> None:
    header = normalize("Room Revenue (EUR)")

    assert header.raw == "Room Revenue (EUR)"
    assert header.text == "room revenue"
    assert header.qualifier == "EUR"


def test_a_header_that_is_only_a_qualifier_is_kept() -> None:
    assert normalize("(EUR)").text == "eur"


@pytest.mark.parametrize(
    "raw", ["N. Camere", "Nr camere", "No. camere", "Num. camere", "Numero camere"]
)
def test_the_word_number_is_written_many_ways(raw: str) -> None:
    assert normalize(raw).words == ("number", "camere")


def test_a_header_written_without_spaces_is_cut_into_known_words() -> None:
    assert normalize("checkindate").words in {("check", "in", "date"), ("checkin", "date")}
    assert field_of(B, "checkindate") == "check_in"
    assert normalize("reservationcode").words == ("reservation", "code")
    assert normalize("codiceprenotazione").words == ("codice", "prenotazione")


def test_an_unknown_long_word_is_not_cut() -> None:
    assert normalize("verylongunknownword").words == ("verylongunknownword",)


def test_normalising_never_raises_on_odd_input() -> None:
    for raw in ("", "   ", "###", "€", "​", "a" * 500, "日本語"):
        assert normalize(raw).raw == raw


# --- matching -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("domain", "raw", "field"),
    [
        (B, "reservation_code", "source_record_id"),
        (B, "booking_status", "status"),
        (B, "room_total", "room_revenue"),
        (B, "CheckInDate", "check_in"),
        (B, "CheckOutDate", "check_out"),
        (B, "RESV_STATUS", "status"),
        (B, "CONFIRMATION_NO", "source_record_id"),
        (B, "Nr. Pratica", "source_record_id"),
        (B, "Data Arrivo", "check_in"),
        (B, "Dal giorno", "check_in"),
        (B, "Provenienza prenotazione", "channel"),
        (L, "Hours Worked", "actual_hours"),
        (L, "Ore previste", "planned_hours"),
        (C, "Totale iva inclusa", "invoice_gross_amount"),
        (C, "P.IVA", "supplier_vat_number"),
    ],
)
def test_plausible_headers_that_no_importer_knows_are_read(
    domain: DataSourceDomain, raw: str, field: str
) -> None:
    assert field_of(domain, raw) == field


def test_the_same_words_in_another_order_are_a_little_less_than_exact() -> None:
    swapped = read_header(B, "Revenue Room").matches["room_revenue"]
    exact = read_header(B, "Room Revenue").matches["room_revenue"]

    assert exact.kind == Kind.EXACT
    assert swapped.kind == Kind.REORDERED
    assert swapped.score < exact.score


def test_a_word_that_only_names_the_kind_of_file_is_not_an_extra_word() -> None:
    match = read_header(B, "Reservation - Arrival").matches["check_in"]

    assert match.kind == Kind.IN_CONTEXT
    assert 0.9 <= match.score < 1.0


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ("Arival Date", "check_in"),
        ("Departur Date", "check_out"),
        ("Reservaton Code", "source_record_id"),
        ("Bookng Date", "booked_at"),
        ("Room Revenu", "room_revenue"),
        ("Channle", "channel"),
        ("Prenotazine", None),  # no phrase is this word alone: nothing to match
    ],
)
def test_a_spelling_mistake_is_still_the_header_it_meant(raw: str, field: str | None) -> None:
    matches = read_header(B, raw).matches

    if field is None:
        assert not matches
        return
    assert matches[field].kind == Kind.TYPO
    assert 0.8 <= matches[field].score < 1.0


# --- near collisions ------------------------------------------------------------------------------


def test_check_in_and_check_out_are_80_percent_alike_as_strings_and_still_different() -> None:
    from rapidfuzz import fuzz

    assert (
        fuzz.ratio("check in", "check out") >= 60
    )  # the trap: letters alone cannot tell them apart
    assert field_of(B, "check in") == "check_in"
    assert field_of(B, "check out") == "check_out"
    assert "check_in" not in read_header(B, "check out").matches
    assert "check_out" not in read_header(B, "check in").matches


@pytest.mark.parametrize(
    ("raw", "wrong"),
    [
        ("Planned Hours", "actual_hours"),
        ("Actual Hours", "planned_hours"),
        ("Net Amount", "invoice_gross_amount"),
        ("Gross Amount", "invoice_net_amount"),
        ("Arrival Date", "check_out"),
        ("Departure Date", "check_in"),
        ("Commission Rate", "commission_amount"),
    ],
)
def test_opposite_headers_are_never_each_others_field(raw: str, wrong: str) -> None:
    domain = {"Planned Hours": L, "Actual Hours": L}.get(raw, B)
    if "Amount" in raw and "Commission" not in raw:
        domain = C
    assert wrong not in read_header(domain, raw).matches


def test_a_typo_cannot_turn_a_header_into_its_opposite() -> None:
    # "Arrivl" is a typo of arrival; it must not become departure whatever the letters share
    matches = read_header(B, "Arrivl Date").matches

    assert "check_out" not in matches
    assert matches["check_in"].kind == Kind.TYPO


@pytest.mark.parametrize(
    ("raw", "blocked"),
    [
        ("ADR", {"room_revenue", "total_revenue"}),
        ("Average Daily Rate", {"room_revenue"}),
        ("Room nights", {"room_revenue", "rooms"}),
        ("Prezzo notte", {"room_revenue"}),
        ("Payment status", {"status"}),
        ("Check in time", {"check_in"}),
    ],
)
def test_a_phrase_that_means_another_thing_blocks_the_field_it_resembles(
    raw: str, blocked: set[str]
) -> None:
    reading = read_header(B, raw)

    assert blocked <= reading.blocked
    assert not (blocked & set(reading.matches))


def test_a_generic_word_says_too_little_to_be_matched() -> None:
    for raw in ("Total amount", "Importo", "Data", "Total", "Price", "Amount"):
        assert not read_header(B, raw).matches, raw


# --- the vocabulary indexed
# ------------------------------------------------------------------------


def test_matching_a_header_is_fast_enough_for_every_column_of_every_upload() -> None:
    import time

    read_header(B, "warm up")
    started = time.perf_counter()
    for _ in range(100):
        read_header(B, "Booking Statuss")
    assert (time.perf_counter() - started) / 100 < 0.01  # 10 ms is generous: it is ~0.1 ms


def test_the_vocabulary_words_are_folded_like_a_header() -> None:
    words = vocabulary_words()

    assert "reservation" in words
    assert "prenotazione" in words
    assert all(w == w.lower() and " " not in w for w in words)


def test_a_glued_header_gets_the_treatment_a_spaced_one_gets() -> None:
    assert normalize("numerocamere").words == ("number", "camere")  # "numero" is "number"
    assert normalize("canaledivendita").words == ("canale", "vendita")  # "di" is not a word
    assert field_of(B, "numerocamere") == "rooms"
    assert field_of(B, "canaledivendita") == "channel"
