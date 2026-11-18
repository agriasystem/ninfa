"""Smart Import V4: the selection engine - what it adds to V3, and what it must never change.

The engine replaces one step of the understanding (which column is which field). These tests pin
the three promises: it reads what V3 could not (camelCase, glued words, a spelling mistake, a unit
after the name, a column with no name at all), it never overrules what V3 already read by a name or
a
rule, and it only ever takes certainty AWAY from a reading V3 would have made - never adds a
certainty a name and values did not earn.
"""

import ast
import os
from pathlib import Path
from typing import Any

import pytest

from app.modules.data_sources.algorithmic import selector
from app.modules.data_sources.algorithmic.engine import (
    DEFAULT,
    HEADER_ONLY,
    AlgorithmicEngine,
    Trace,
)
from app.modules.data_sources.proposal import propose
from app.modules.data_sources.semantics import DomainSem, Level
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from tests.algorithmic_support import (
    CHANNELS,
    DEPARTMENTS,
    MONEY,
    ROOMS,
    STATUSES,
    codes,
    fields_of,
    levels_of,
    read,
    stay,
    table,
)

booked, arrival, departure = stay()


def bookings(**headers: str) -> dict[str, list[Any]]:
    """A bookings table whose headers are given by field (default: a neutral unknown name)."""
    values: dict[str, list[Any]] = {
        "id": list(codes()),
        "booked": list(booked),
        "in": list(arrival),
        "out": list(departure),
        "status": list(STATUSES),
        "channel": list(CHANNELS),
        "rooms": list(ROOMS),
        "revenue": list(MONEY),
    }
    return {
        headers.get(key, f"Campo {i}"): column for i, (key, column) in enumerate(values.items())
    }


# --- what V4 reads and V3 could not ---------------------------------------------------------------

CAMEL = {
    "id": "ReservationCode",
    "booked": "BookingDate",
    "in": "CheckInDate",
    "out": "CheckOutDate",
    "status": "BookingStatus",
    "channel": "SalesChannel",
    "rooms": "NumberOfRooms",
    "revenue": "RoomTotal",
}
EXPECTED = {
    "id": "source_record_id",
    "booked": "booked_at",
    "in": "check_in",
    "out": "check_out",
    "status": "status",
    "channel": "channel",
    "rooms": "rooms",
    "revenue": "room_revenue",
}


def test_the_three_named_headers_are_read_by_both_engines() -> None:
    named = bookings(id="reservation_code", status="booking_status", revenue="room_total")

    for config in (None, DEFAULT):
        found = fields_of(read(BOOKINGS, named, config))
        assert found["reservation_code"] == "source_record_id"
        assert found["booking_status"] == "status"
        assert found["room_total"] == "room_revenue"


def test_camel_case_headers_are_read_by_v4_and_not_completely_by_v3() -> None:
    table_ = bookings(**CAMEL)

    v4 = read(BOOKINGS, table_, DEFAULT)
    v3 = read(BOOKINGS, table_, None)

    assert {h: f for h, f in fields_of(v4).items()} == {CAMEL[k]: EXPECTED[k] for k in CAMEL}
    assert set(levels_of(v4).values()) == {"HIGH"}
    assert fields_of(v3) != fields_of(v4) or set(levels_of(v3).values()) != {"HIGH"}


def test_words_written_without_spaces_are_read() -> None:
    glued = bookings(
        id="reservationcode",
        booked="bookingdate",
        **{"in": "checkindate", "out": "checkoutdate"},
        status="bookingstatus",
        channel="channelname",
        rooms="roomcount",
        revenue="roomrevenue",
    )

    assert set(fields_of(read(BOOKINGS, glued, DEFAULT)).values()) == set(EXPECTED.values())


def test_a_unit_or_a_mark_after_the_name_is_set_aside() -> None:
    qualified = bookings(
        id="Reservation Code *",
        booked="Booking Date (dd/mm/yyyy)",
        **{"in": "Check-in (date)"},
        out="Check-out (date)",
        status="Status (PMS)",
        channel="Channel (OTA)",
        rooms="Rooms #",
        revenue="Room Revenue (EUR)",
    )

    proposal = read(BOOKINGS, qualified, DEFAULT)

    assert set(fields_of(proposal).values()) == set(EXPECTED.values())
    assert set(levels_of(proposal).values()) == {"HIGH"}


def test_a_spelling_mistake_is_read_but_never_made_certain() -> None:
    typo = bookings(
        id="Reservaton Code",
        booked="Booking Dat",
        **{"in": "Arival Date"},
        out="Departur Date",
        status="Booking Statuss",
        channel="Channle",
        rooms="Number of Roms",
        revenue="Room Revenu",
    )

    proposal = read(BOOKINGS, typo, DEFAULT)

    assert set(fields_of(proposal).values()) == set(EXPECTED.values())
    # a typo is a reading, not a proof: the person is asked (at most MEDIUM), never HIGH
    assert Level.HIGH not in {
        c.level for c in proposal.columns if c.name and c.name.value == "FUZZY"
    }
    assert any(level != "HIGH" for level in levels_of(proposal).values())


# --- a column with no name at all
# -------------------------------------------------------------------


def test_the_values_alone_name_a_status_and_a_booking_code_at_medium() -> None:
    nameless = bookings(
        booked="Booking Date",
        **{"in": "Check in"},
        out="Check out",
        rooms="Rooms",
        revenue="Room Revenue",
        channel="Channel",
    )

    proposal = read(BOOKINGS, nameless, DEFAULT)
    found = {c.field: c for c in proposal.columns if c.field}

    assert found["status"].level == Level.MEDIUM
    assert found["source_record_id"].level == Level.MEDIUM
    assert all(
        c.name and c.name.value == "VALUES"
        for f, c in found.items()
        if f in {"status", "source_record_id"}
    )


def test_a_channel_is_never_named_by_its_values_alone() -> None:
    """A product decision of an earlier gate (`test_the_values_alone_never_make_a_channel_without_a_
    header_that_says_so`): the values of a column may fit a channel, they never make one."""
    nameless = bookings(
        id="Reservation Code",
        booked="Booking Date",
        **{"in": "Check in"},
        out="Check out",
        status="Status",
        rooms="Rooms",
        revenue="Room Revenue",
    )

    found = {c.field for c in read(BOOKINGS, nameless, DEFAULT).columns if c.field}

    assert "channel" not in found


def test_a_known_header_is_never_read_as_another_thing_by_its_values() -> None:
    """The header "Centro di costo" is where a cost is booked, not a department: its values may be
    department words and still it is not one (a product decision pinned by `test_a_cost_centre_is_
    not_an_operating_centre`). Only a header that says NOTHING leaves a column to its values."""
    rota = {
        "Data": [f"2026-10-{d:02d}" for d in range(1, 13)],
        "Ore previste": [8, 6, 8, 7, 6, 8, 8, 6, 7, 8, 6, 8],
        "Ore effettive": [8, 6, 8, 7, 6, 8, 8, 6, 7, 8, 6, 8],
    }

    cost_centre = {**rota, "Centro di costo": list(DEPARTMENTS)}
    nameless = {**rota, "Campo 4": list(DEPARTMENTS)}

    assert fields_of(read(LABOR, cost_centre, DEFAULT))["Centro di costo"] != "role"
    assert fields_of(read(LABOR, nameless, DEFAULT))["Campo 4"] == "role"


def test_a_bare_code_over_repeated_values_is_asked_about_not_dropped() -> None:
    """V3 asks one question about a reference that repeats (a group, a company); V4 must not turn
    that question into nothing (`test_a_bare_code_column_over_repeated_values_is_confirmed_with_one_
    question`)."""
    repeated = {"Pratica": ["A1", "A1", "A2", "A2", "A3", "A3"] * 2, "Stato": list(STATUSES)}

    v3 = fields_of(read(BOOKINGS, repeated, None))["Pratica"]
    v4 = fields_of(read(BOOKINGS, repeated, DEFAULT))["Pratica"]

    assert v4 == v3


def test_three_unnamed_dates_in_order_are_named_by_their_relation_at_medium() -> None:
    nameless = bookings(
        id="Reservation Code",
        status="Status",
        channel="Channel",
        rooms="Rooms",
        revenue="Room Revenue",
    )

    found = {c.field: c for c in read(BOOKINGS, nameless, DEFAULT).columns if c.field}

    assert (found["booked_at"].header, found["check_in"].header, found["check_out"].header) == (
        "Campo 1",
        "Campo 2",
        "Campo 3",
    )
    assert {found[f].level for f in ("booked_at", "check_in", "check_out")} == {Level.MEDIUM}


def test_a_reading_from_the_values_alone_is_never_certain() -> None:
    for domain_table, sem in ((bookings(), BOOKINGS),):
        proposal = read(sem, domain_table, DEFAULT)
        assert all(c.level != Level.HIGH for c in proposal.columns if c.field)


def test_v3_reads_none_of_those_nameless_columns() -> None:
    nameless = bookings(
        booked="Booking Date",
        **{"in": "Check in"},
        out="Check out",
        rooms="Rooms",
        revenue="Room Revenue",
    )

    v3 = {c.field for c in read(BOOKINGS, nameless, None).columns if c.field}

    assert not v3 & {"status", "channel", "source_record_id"}


def test_a_header_only_engine_does_not_read_a_column_by_its_values() -> None:
    nameless = bookings(
        booked="Booking Date",
        **{"in": "Check in"},
        out="Check out",
        rooms="Rooms",
        revenue="Room Revenue",
    )

    header_only = {c.field for c in read(BOOKINGS, nameless, HEADER_ONLY).columns if c.field}

    assert not header_only & {"status", "channel", "source_record_id"}


# --- negative evidence ----------------------------------------------------------------------------


def test_channel_names_under_a_status_header_are_not_a_status() -> None:
    wrong = {"Reservation Code": codes(), "Stato": list(CHANNELS)}

    assert "status" not in fields_of(read(BOOKINGS, wrong, DEFAULT)).values()


def test_departments_under_a_channel_header_are_not_a_channel() -> None:
    wrong = {"Reservation Code": codes(), "Canale": list(DEPARTMENTS)}

    assert fields_of(read(BOOKINGS, wrong, DEFAULT))["Canale"] is None


def test_a_rate_per_night_is_not_the_room_revenue() -> None:
    adr = {"Reservation Code": codes(), "ADR": list(MONEY)}

    assert fields_of(read(BOOKINGS, adr, DEFAULT))["ADR"] is None


def test_room_nights_are_not_a_room_count() -> None:
    nights = {"Reservation Code": codes(), "Room nights": [1, 2, 3, 2, 1, 4, 2, 3, 1, 2, 5, 2]}

    assert fields_of(read(BOOKINGS, nights, DEFAULT))["Room nights"] is None


# --- what V4 never changes -----------------------------------------------------------------------


def test_a_header_v3_reads_by_a_name_or_a_rule_is_read_the_same_way() -> None:
    register = table(
        {
            "Data": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
            "N. documento": ["2026/101", "2026/102", "2026/103", "2026/104"],
            "Fornitore": ["Rossi Srl", "Bianchi Spa", "Rossi Srl", "Verdi Snc"],
            "Descrizione": ["Luce", "Acqua", "Gas", "Pulizie"],
            "Imponibile": [100.0, 250.0, 80.0, 120.0],
        }
    )

    v3 = {c.header: (c.field, c.level) for c in propose(COSTS, register).columns}
    v4 = {
        c.header: (c.field, c.level)
        for c in propose(COSTS, register, engine=AlgorithmicEngine(DEFAULT)).columns
    }

    assert v4 == v3
    assert v4["Imponibile"][0] == "line_total"  # a register's net amount is a LINE amount


def test_total_stay_stays_the_room_revenue() -> None:
    columns = {"Reservation Code": codes(), "Totale soggiorno": list(MONEY)}

    assert fields_of(read(BOOKINGS, columns, DEFAULT))["Totale soggiorno"] == "room_revenue"


@pytest.mark.parametrize("sem", [BOOKINGS, LABOR, COSTS])
def test_personal_data_is_locked_exactly_as_before(sem: DomainSem) -> None:
    people = {"Ospite": ["Mario Rossi", "Anna Verdi", "Luca Neri", "Paola Gialli"] * 3}

    v4 = propose(sem, table(people), engine=AlgorithmicEngine(DEFAULT))
    v3 = propose(sem, table(people))

    assert [(c.locked, c.field) for c in v4.columns] == [(c.locked, c.field) for c in v3.columns]


def test_the_evidence_of_a_reading_never_contains_a_value_of_the_file() -> None:
    secret = "ZZ-SECRET-CODE"
    columns = {
        "Reservation Code": [f"{secret}-{i:03d}" for i in range(12)],
        "Stato": list(STATUSES),
    }

    seen: list[Trace] = []
    engine = AlgorithmicEngine(DEFAULT, on_trace=seen.append)
    proposal = propose(BOOKINGS, table(columns), engine=engine)

    text = " ".join(" ".join(c.evidence) for c in proposal.columns)
    text += " ".join(str(s.breakdown()) for t in seen for s in t.scores)
    assert secret not in text


def test_a_pair_two_columns_claim_equally_is_not_certain() -> None:
    twin = {
        "Reservation Code": codes(),
        "Check in": list(arrival),
        "Check out": list(departure),
        "Arrival": list(arrival),
    }

    found = {c.header: c for c in read(BOOKINGS, twin, DEFAULT).columns}

    assert found["Check in"].level != Level.HIGH or found["Arrival"].field is None


def test_every_certainty_v4_gives_is_one_v3_would_have_given_for_the_same_name() -> None:
    """V4 may add readings and remove certainty: a HIGH it gives a header V3 reads is V3's HIGH."""
    named = bookings(
        id="Codice prenotazione",
        booked="Data prenotazione",
        **{"in": "Check-in"},
        out="Check-out",
        status="Stato",
        channel="Canale",
        rooms="Camere",
        revenue="Ricavo camera",
    )

    v3 = {c.header: c.level for c in read(BOOKINGS, named, None).columns}
    v4 = {c.header: c.level for c in read(BOOKINGS, named, DEFAULT).columns}

    for header, level in v4.items():
        if level == Level.HIGH:
            assert v3[header] == Level.HIGH


# --- the ablation configurations -----------------------------------------------------------------


def test_the_configurations_are_cumulative() -> None:
    assert (HEADER_ONLY.header, HEADER_ONLY.values) == (True, False)
    assert (DEFAULT.header, DEFAULT.values) == (True, True)


def test_only_the_engines_that_were_kept_can_be_selected() -> None:
    """The SciPy assignment and the margin demotion were measured and removed (ADR 0056): they are
    not engines, not configurations and not a name the setting accepts."""
    assert set(selector.ENGINES) == {"v3", "v4", "v4-header"}
    for removed in ("v4-assign", "v4-margin"):
        with pytest.raises(ValueError):
            selector.configure(removed)
    assert not hasattr(DEFAULT, "assignment")


def test_a_trace_explains_every_candidate_with_its_parts() -> None:
    seen: list[Trace] = []
    propose(
        BOOKINGS, table(bookings(**CAMEL)), engine=AlgorithmicEngine(DEFAULT, on_trace=seen.append)
    )

    scores = seen[0].scores
    status = next(s for s in scores if s.field == "status" and s.column == 4)
    assert status.header_kind == "EXACT"  # a name the importer already knows: V3 reads it
    assert {"total", "header", "values", "proof", "relational", "veto"} <= set(status.breakdown())
    assert seen[0].selected[4][0] == "status"


def test_a_reading_by_the_vocabulary_names_the_phrase_it_matched() -> None:
    seen: list[Trace] = []
    columns = {"Reservation Code": codes(), "Arival Date": list(arrival)}
    propose(BOOKINGS, table(columns), engine=AlgorithmicEngine(DEFAULT, on_trace=seen.append))

    date_ = next(s for s in seen[0].scores if s.field == "check_in" and s.column == 1)
    assert date_.header_kind == "TYPO"
    assert date_.phrase == "arrival date"


# --- which engine reads ---------------------------------------------------------------------------


def test_the_default_engine_is_v3() -> None:
    saved = list(selector._configured)
    selector._configured.clear()
    try:
        os.environ.pop(selector.ENV_NAME, None)
        assert selector.current_name() == "v3"
    finally:
        selector._configured[:] = saved


def test_an_engine_can_be_chosen_for_a_block_of_code_only() -> None:
    before = selector.current_name()
    with selector.use_engine("v4"):
        assert selector.current_name() == "v4"
        with selector.use_engine("v3"):
            assert selector.current_name() == "v3"
        assert selector.current_name() == "v4"
    assert selector.current_name() == before


def test_an_unknown_engine_is_an_error_not_a_silent_fallback() -> None:
    with pytest.raises(ValueError, match="unknown understanding engine"):
        selector.configure("v5")
    with (
        pytest.raises(ValueError, match="unknown understanding engine"),
        selector.use_engine("fast"),
    ):
        pass


def test_the_selector_gives_the_same_reading_as_calling_the_engine_directly() -> None:
    columns = table(bookings(**CAMEL))
    with selector.use_engine("v4"):
        through = selector.propose(BOOKINGS, columns)
    direct = propose(BOOKINGS, columns, engine=AlgorithmicEngine(DEFAULT))

    assert [(c.header, c.field, c.level) for c in through.columns] == [
        (c.header, c.field, c.level) for c in direct.columns
    ]


# --- no model, ever -------------------------------------------------------------------------------


def test_the_algorithmic_package_imports_no_model_client() -> None:
    package = Path(selector.__file__).parent
    imported: set[str] = set()
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert not imported & {
        "openai",
        "anthropic",
        "httpx",
        "httpx2",
        "requests",
        "urllib3",
        "socket",
    }
    assert "app" in imported and "rapidfuzz" in imported
    assert not imported & {"scipy", "duckdb", "clevercsv", "fsspec"}


def test_reading_a_file_with_v4_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    opened: list[Any] = []
    real = socket.socket.connect

    def spy(self: socket.socket, address: object) -> None:
        opened.append(address)
        real(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", spy)

    read(BOOKINGS, bookings(**CAMEL), DEFAULT)
    read(BOOKINGS, bookings(), DEFAULT)

    assert opened == []


def test_two_columns_that_say_the_same_thing_stay_contested_as_in_v3() -> None:
    """UK022 of the unseen-file benchmark: "Issue date" next to "Invoice date". V3 does not pick
    one (they satisfy the same rule, so both are CONTESTED and the person is asked); a reading by
    the vocabulary must not make that protection disappear - it was the one unsafe READY V4 had."""
    days = [f"2026-10-{d:02d}" for d in range(1, 13)]
    register = {
        "Billed By": ["Rossi Srl", "Bianchi Spa", "Verdi Snc"] * 4,
        "Document No.": [f"2026/{100 + i}" for i in range(12)],
        "Memo": ["Luce", "Acqua", "Gas"] * 4,
        "Issue date": days,
        "Invoice date": days,
        "Net Amount": [100.0 + i for i in range(12)],
    }

    for config in (None, DEFAULT):
        proposal = read(COSTS, register, config)
        found = {c.header: c for c in proposal.columns}

        assert found["Issue date"].field is None, config
        assert found["Invoice date"].field is None, config
        assert found["Issue date"].ambiguous_group == "CONTESTED", config
        assert found["Invoice date"].ambiguous_group == "CONTESTED", config


# --- the whole understanding, with a model listening ----------------------------------------------


def _csv_of(columns: dict[str, Any]) -> bytes:
    lines = [";".join(columns)]
    lines += [";".join(str(v) for v in row) for row in zip(*columns.values(), strict=True)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_a_standard_v4_import_asks_no_model_and_the_same_file_would_ask_one_in_assist() -> None:
    """The brief: a normal V4 understanding makes NO request to OpenAI. The control is the same file
    with the semantic layer ASSIST (what the pilot has never turned on): it does ask, so the zero
    above means something."""
    from uuid import UUID

    from app.core.tenant import TenantContext
    from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
    from app.modules.ai.import_understanding.types import AiMode
    from app.modules.data_sources.smart_import import SmartImportService
    from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
    from app.modules.ingestion.models import DataSourceDomain
    from tests.import_ai_support import Recorder

    content = _csv_of(bookings(booked="Booking Date", **{"in": "Check in"}, out="Check out"))

    def understand(mode: AiMode, recorder: Recorder) -> None:
        tenant = TenantContext(UUID(int=1))
        session: Any = None
        service = UnderstandingService(
            session,
            tenant,
            SmartImportService(session, tenant),
            ImportUnderstandingResolver(recorder, mode),
        )
        with selector.use_engine("v4"):
            service.understand(
                DataSourceDomain.BOOKINGS,
                "export.csv",
                content,
                UnderstandAnswers(),
                False,
                None,
                False,
                currency="EUR",
            )

    standard, control = Recorder(), Recorder()
    understand(AiMode.OFF, standard)
    understand(AiMode.ASSIST, control)

    assert standard.requests == []  # the normal path: no model, no request, no cost
    assert control.requests, "the control must ask, or this test proves nothing"


def test_the_default_settings_select_no_model_and_the_v3_engine() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields

    assert fields["smart_import_ai_mode"].default == "off"
    assert fields["import_understanding_provider"].default == "unconfigured"
    assert fields["smart_import_understanding_engine"].default == "v3"


# --- what V3 reads, V4 keeps reading --------------------------------------------------------------


def test_v3s_likeness_of_letters_stands_when_every_other_reading_is_ruled_out() -> None:
    """`P.IVA forn.` over VAT numbers: its word rule reads a tax AMOUNT, which the values rule out;
    V3 is left with its likeness of letters (a LOW supplier VAT number). V4 must not lose it."""
    register = {
        "Fornitore": ["Rossi Srl", "Bianchi Spa", "Verdi Snc"] * 4,
        "P.IVA forn.": [f"IT0{1234567890 + i}" for i in range(12)],
        "Descrizione": ["Luce", "Acqua", "Gas"] * 4,
    }

    v3 = fields_of(read(COSTS, register, None))["P.IVA forn."]
    v4 = fields_of(read(COSTS, register, DEFAULT))["P.IVA forn."]

    assert v3 == v4 == "supplier_vat_number"


def test_v3s_lone_date_column_is_still_read_whatever_its_header_says() -> None:
    """A lone "Data" over dates is probably the arrival (V3's own value-only rule, MEDIUM). The
    "the header says nothing" gate is for the readings V4 ADDS, not for this one."""
    file = {
        "Reservation Code": codes(),
        "Data": list(arrival),
        "Stato": list(STATUSES),
    }

    v3 = {c.header: (c.field, c.level) for c in read(BOOKINGS, file, None).columns}
    v4 = {c.header: (c.field, c.level) for c in read(BOOKINGS, file, DEFAULT).columns}

    assert v4["Data"] == v3["Data"] == ("check_in", Level.MEDIUM)


def test_a_vat_number_is_not_a_tax_amount() -> None:
    """V3 reads `P.IVA forn.` over plain 11-digit numbers as an invoice TAX AMOUNT (HIGH); the
    vocabulary and the values read a supplier VAT number."""
    register = {
        "Fornitore": ["Rossi Srl", "Bianchi Spa", "Verdi Snc"] * 4,
        "P.IVA forn.": [f"0{1234567890 + i}" for i in range(12)],
    }

    assert fields_of(read(COSTS, register, DEFAULT))["P.IVA forn."] == "supplier_vat_number"
