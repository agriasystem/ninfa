"""Mapping suggestions, the mapping configuration and the header signature (no database)."""

from typing import Any

import pytest

from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import (
    CanonicalField,
    MappingConfig,
    check_schema,
    compute_header_signature,
    find_duplicate_headers,
)
from app.modules.bookings.models import BookingStatus, ChannelType
from app.modules.bookings.suggestions import (
    SuggestionConfidence,
    SuggestionReason,
    suggest_mapping,
)
from tests.booking_support import STANDARD_COLUMNS, STANDARD_HEADERS, make_config

F = CanonicalField


def by_field(headers: list[str]) -> dict[CanonicalField, Any]:
    return {s.canonical_field: s for s in suggest_mapping(headers)}


# --- suggestions (tests 15-17) ---------------------------------------------------------------


def test_italian_headers_are_recognised_by_known_alias() -> None:
    suggestions = by_field(
        [
            "ID Prenotazione",
            "Data Prenotazione",
            "Data Arrivo",
            "Data Partenza",
            "Stato",
            "Camere",
            "Importo Camera",
            "Canale",
            "Note Ospite",
        ]
    )

    expected = {
        F.SOURCE_RECORD_ID: "ID Prenotazione",
        F.BOOKED_AT: "Data Prenotazione",
        F.CHECK_IN: "Data Arrivo",
        F.CHECK_OUT: "Data Partenza",
        F.STATUS: "Stato",
        F.ROOMS: "Camere",
        F.ROOM_REVENUE: "Importo Camera",
        F.CHANNEL: "Canale",
    }
    for field, column in expected.items():
        suggestion = suggestions[field]
        assert suggestion.suggested_source_column == column
        assert (suggestion.confidence, suggestion.reason) == (
            SuggestionConfidence.HIGH,
            SuggestionReason.KNOWN_ALIAS,
        )


def test_english_headers_are_recognised_by_known_alias() -> None:
    suggestions = by_field(
        [
            "Reservation ID",
            "Created At",
            "Arrival Date",
            "Departure Date",
            "Booking Status",
            "Number of Rooms",
            "Room Revenue",
            "Booking Source",
            "Guests",
            "Total Amount",
            "Commission Rate",
            "Cancellation Date",
            "Room Type",
            "Rate Plan",
        ]
    )

    assert suggestions[F.CHECK_IN].suggested_source_column == "Arrival Date"
    assert suggestions[F.CHECK_OUT].suggested_source_column == "Departure Date"
    assert suggestions[F.CHANNEL].suggested_source_column == "Booking Source"
    assert suggestions[F.GUESTS].suggested_source_column == "Guests"
    assert suggestions[F.TOTAL_REVENUE].suggested_source_column == "Total Amount"
    assert suggestions[F.COMMISSION_RATE].suggested_source_column == "Commission Rate"
    assert suggestions[F.CANCELLED_AT].suggested_source_column == "Cancellation Date"
    matched = [s for s in suggestions.values() if s.suggested_source_column]
    assert len(matched) == 14
    assert all(s.confidence == SuggestionConfidence.HIGH for s in matched)
    assert suggestions[F.COMMISSION_AMOUNT].confidence == SuggestionConfidence.NONE


def test_case_accents_and_punctuation_do_not_matter() -> None:
    suggestions = by_field(["CHECK-IN", "check_out", "  N. Camere  "])

    assert suggestions[F.CHECK_IN].confidence == SuggestionConfidence.HIGH
    assert suggestions[F.CHECK_OUT].suggested_source_column == "check_out"


def test_a_similar_header_is_only_a_fuzzy_suggestion_never_high() -> None:
    suggestion = by_field(["Reservation Idd"])[F.SOURCE_RECORD_ID]

    assert suggestion.suggested_source_column == "Reservation Idd"
    assert suggestion.reason == SuggestionReason.FUZZY_MATCH
    assert suggestion.confidence in (SuggestionConfidence.MEDIUM, SuggestionConfidence.LOW)
    assert 0.78 <= suggestion.score < 1.0


def test_unrelated_headers_get_no_suggestion() -> None:
    suggestions = suggest_mapping(["Guest Name", "Passport", "Telefono", "Note interne"])

    assert all(s.suggested_source_column is None for s in suggestions)
    assert {s.reason for s in suggestions} == {SuggestionReason.NO_MATCH}


def test_every_field_is_reported_once_and_a_header_is_used_at_most_once() -> None:
    suggestions = suggest_mapping(["Total", "Revenue", "Camera", "Camere"])
    columns = [s.suggested_source_column for s in suggestions if s.suggested_source_column]

    assert [s.canonical_field for s in suggestions] == list(CanonicalField)
    assert len(columns) == len(set(columns))
    by = {s.canonical_field: s.suggested_source_column for s in suggestions}
    assert (by[F.ROOMS], by[F.ROOM_TYPE]) == ("Camere", "Camera")


def test_suggestions_are_deterministic() -> None:
    headers = ["Data Arrivo", "Arrival Dt", "Id", "Reference", "Stato", "Status"]

    assert suggest_mapping(headers) == suggest_mapping(list(headers))


# --- mapping configuration (tests 18-20) -----------------------------------------------------


def invalid(data: dict[str, Any]) -> BookingImportError:
    with pytest.raises(BookingImportError) as info:
        MappingConfig.parse(data)
    assert info.value.error_code == BookingErrorCode.INVALID_MAPPING
    return info.value


def test_a_complete_mapping_is_valid_and_round_trips_through_storage() -> None:
    config = make_config(
        add_columns={"guests": {"column": "Pax"}, "room_type": {"column": "Room Type"}},
        status_mapping={"Confirmed OK": "CONFIRMED"},
        channel_mapping={"BKG": {"name": "Booking.com", "channel_type": "OTA"}},
        format_options={"decimal_separator": ",", "thousands_separator": "."},
    )

    assert MappingConfig.parse(config.to_stored()) == config
    assert config.mapped_columns()[F.GUESTS] == "Pax"


@pytest.mark.parametrize(
    "missing",
    [
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "status",
        "rooms",
        "room_revenue",
        "channel",
    ],
)
def test_every_required_field_must_be_mapped(missing: str) -> None:
    columns = {k: v for k, v in STANDARD_COLUMNS.items() if k != missing}

    error = invalid({"column_mapping": columns})

    assert missing in str(error.details)


def test_optional_fields_may_be_left_unmapped() -> None:
    assert make_config().mapped_columns().keys() == {F(k) for k in STANDARD_COLUMNS}


def test_constants_are_supported_for_rooms_status_and_channel() -> None:
    config = make_config(
        add_columns={
            "rooms": {"constant": 1},
            "status": {"constant": "CONFIRMED"},
            "channel": {"constant": "Direct"},
        }
    )

    assert config.constants() == {F.ROOMS: 1, F.STATUS: "CONFIRMED", F.CHANNEL: "Direct"}
    assert F.ROOMS not in config.mapped_columns()


@pytest.mark.parametrize(
    "field",
    [
        "source_record_id",
        "booked_at",
        "check_in",
        "check_out",
        "room_revenue",
        "guests",
        "total_revenue",
        "commission_amount",
        "commission_rate",
        "cancelled_at",
        "room_type",
        "rate_plan",
    ],
)
def test_constants_are_refused_where_they_would_invent_data(field: str) -> None:
    error = invalid({"column_mapping": {**STANDARD_COLUMNS, field: {"constant": "X"}}})

    assert "cannot be a constant" in str(error.details)


@pytest.mark.parametrize(
    ("field", "constant"),
    [("rooms", 0), ("rooms", "abc"), ("status", "Pending guarantee"), ("channel", "---")],
)
def test_constants_must_be_meaningful(field: str, constant: Any) -> None:
    invalid({"column_mapping": {**STANDARD_COLUMNS, field: {"constant": constant}}})


def test_a_field_needs_exactly_one_source() -> None:
    invalid({"column_mapping": {**STANDARD_COLUMNS, "guests": {}}})
    invalid({"column_mapping": {**STANDARD_COLUMNS, "guests": {"column": "A", "constant": 1}}})
    invalid({"column_mapping": {**STANDARD_COLUMNS, "unknown_field": {"column": "A"}}})


def test_a_status_constant_can_use_the_profiles_own_status_mapping() -> None:
    config = make_config(
        add_columns={"status": {"constant": "Provisorio"}},
        status_mapping={"provisorio": "CONFIRMED"},
    )

    assert config.constants()[F.STATUS] == "Provisorio"


def test_status_and_channel_keys_are_normalised_and_conflicts_rejected() -> None:
    config = make_config(
        status_mapping={"No-Show": "NO_SHOW"},
        channel_mapping={"BOOKING.COM": {"channel_type": "OTA"}},
    )

    assert config.status_mapping == {"no show": BookingStatus.NO_SHOW}
    assert list(config.channel_mapping) == ["booking com"]
    invalid(
        {
            "column_mapping": STANDARD_COLUMNS,
            "status_mapping": {"No-Show": "NO_SHOW", "no show": "CANCELLED"},
        }
    )
    invalid({"column_mapping": STANDARD_COLUMNS, "status_mapping": {"x": "PENDING"}})
    invalid(
        {"column_mapping": STANDARD_COLUMNS, "channel_mapping": {"a": {"channel_type": "PORTAL"}}}
    )


@pytest.mark.parametrize(
    "options",
    [
        {"date_formats": {"check_in": "%d/%m/%y"}},  # two-digit year
        {"date_formats": {"check_in": "%d/%m"}},  # no year
        {"date_formats": {"check_in": "%d %B %Y"}},  # month names are locale dependent
        {"date_formats": {"check_in": "%d/%m/%Y %z"}},
        {"date_formats": {"rooms": "%d/%m/%Y"}},  # not a date field
        {"date_formats": {"check_in": "%d/%m/%Y;%H"}},  # arbitrary literal
        {"decimal_separator": ",", "thousands_separator": ","},
        {"delimiter": "|"},
        {"encoding": "latin-1"},
        {"unknown_option": True},
    ],
)
def test_format_options_are_a_closed_explicit_set(options: dict[str, Any]) -> None:
    invalid({"column_mapping": STANDARD_COLUMNS, "format_options": options})


def test_valid_format_options_are_accepted() -> None:
    options = {
        "sheet_name": "Prenotazioni",
        "delimiter": ";",
        "encoding": "cp1252",
        "date_formats": {"check_in": "%d/%m/%Y", "booked_at": "%d/%m/%Y %H:%M"},
        "decimal_separator": ",",
        "thousands_separator": ".",
    }

    config = make_config(format_options=options)

    assert config.format_options.date_formats[F.BOOKED_AT] == "%d/%m/%Y %H:%M"


# --- header signature and schema change (tests 21-22) ----------------------------------------


def test_signature_ignores_column_order_case_and_punctuation() -> None:
    reference = compute_header_signature(STANDARD_HEADERS)

    assert compute_header_signature(reversed(STANDARD_HEADERS)) == reference
    assert compute_header_signature(h.upper() for h in STANDARD_HEADERS) == reference
    assert compute_header_signature([*STANDARD_HEADERS, "Extra"]) != reference
    assert len(reference) == 64 and reference == reference.lower()


def test_a_matching_schema_reuses_the_mapping() -> None:
    check = check_schema(
        make_config(), compute_header_signature(STANDARD_HEADERS), STANDARD_HEADERS
    )

    assert (check.compatible, check.signature_matches, check.missing_columns) == (True, True, ())


def test_unrelated_extra_columns_do_not_invalidate_the_mapping() -> None:
    headers = [*STANDARD_HEADERS, "Guest Email", "Notes"]

    check = check_schema(make_config(), compute_header_signature(STANDARD_HEADERS), headers)

    assert check.compatible is True
    assert check.signature_matches is False


def test_a_missing_mapped_column_means_the_source_schema_changed() -> None:
    headers = [h if h != "Check-in" else "Arrival" for h in STANDARD_HEADERS]

    check = check_schema(make_config(), compute_header_signature(STANDARD_HEADERS), headers)

    assert check.compatible is False
    assert check.missing_columns == ("Check-in",)


def test_a_mapped_column_matches_regardless_of_case_and_spacing() -> None:
    headers = [
        "booking id",
        "BOOKED AT",
        "check in",
        "Check_Out",
        "STATUS",
        "rooms",
        "room revenue",
        "channel",
    ]

    assert check_schema(make_config(), "0" * 64, headers).compatible is True


def test_duplicate_headers_are_found_after_normalisation() -> None:
    assert find_duplicate_headers(["A", "B", "a", "", ""]) == ["a"]
    assert find_duplicate_headers(["Check-in", "Check in"]) == ["check in"]
    assert find_duplicate_headers(["A", "B", ""]) == []


def test_channel_type_enum_is_accepted_by_name_in_the_channel_mapping() -> None:
    config = make_config(channel_mapping={"x": {"channel_type": "TOUR_OPERATOR"}})

    assert config.channel_mapping["x"].channel_type == ChannelType.TOUR_OPERATOR
