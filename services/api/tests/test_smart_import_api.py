"""Smart Import V2 over HTTP: the hotel's OWN CSV / Excel file, its columns matched by the person.

    POST .../import-inspection      read a file, propose what each column means (writes nothing)
    POST .../import-mapping-check   is this matching enough? (the backend's own rules)
    POST .../import-validation      judge every row with this matching, as the import will
    POST .../imports/mapped         import with it, remember it once the import succeeded
    GET / DELETE .../{id}/import-configuration   what was remembered / forget it

What is pinned here: the backend decides what is required (the page never does); nothing is written
until an import is confirmed AND succeeds (no source, no job, no saved configuration before that);
a failed import keeps no new configuration and never spoils a good one; a saved configuration is
recognised by the columns of the file and never by its name; a configuration made for another
version of NINFA's rules is never applied silently; everything is scoped to the workspace and the
property; the file limits hold.
"""

import json
from collections.abc import Callable
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.modules.bookings.parsers as parsers
from app.modules.data_sources.files import MAX_FILE_BYTES
from app.modules.labor.models import LaborEntry
from tests.booking_support import xlsx_bytes
from tests.data_sources_support import (
    SourcesEnv,
    booking_bytes,
    card,
    labor_bytes,
    raw,
    sources_env,
)
from tests.smart_import_support import (
    BOOKINGS_IT_DECISION,
    LABOR_IT_DECISION,
    b64,
    bookings_it_file,
    by_header,
    check_mapping,
    csv_bytes,
    decision,
    import_mapped,
    inspect,
    inspection,
    labor_it_file,
    post_json,
    validation,
    writes,
)
from tests.support import BookingFactory

# The staff file of the brief, with its team column left out: day, person, hours, hourly rate.
NO_TEAM = ["Giorno", "Nome dipendente", "Ore turno", "Costo orario"]
STAFF_FIXED_TEAM = decision(
    {
        "Giorno": "work_date",
        "Nome dipendente": None,
        "Ore turno": "planned_hours",
        "Costo orario": None,
    },
    constants={"labor_category": "FRONT_OFFICE"},
    date_order="DMY",
)


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


# --- reading a file -----------------------------------------------------------------------------


def test_an_italian_staff_file_gets_a_proposal_for_the_columns_ninfa_knows(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = inspection(api_client, env, "LABOR", "turni-settimana-43.csv", labor_it_file())
    columns = by_header(body)

    assert body["file_type"] == "CSV" and body["problem"] is None
    assert (columns["Giorno"]["field"], columns["Giorno"]["level"]) == ("work_date", "RECOGNIZED")
    assert columns["Ore turno"]["field"] == "planned_hours"
    assert columns["Reparto"]["field"] == "role"  # a team in the hotel's words is a role
    assert columns["Giorno"]["examples"] == ["26/10/2026", "27/10/2026", "28/10/2026"]
    assert body["suggestion_complete"] is True and body["already_canonical"] is False


def test_a_persons_name_and_an_hourly_rate_are_shown_but_never_proposed_as_anything(
    api_client: TestClient, env: SourcesEnv
) -> None:
    columns = by_header(inspection(api_client, env, "LABOR", "t.csv", labor_it_file()))

    assert columns["Nome dipendente"]["field"] is None
    assert columns["Nome dipendente"]["not_used_reason"] == "PERSON"
    assert columns["Costo orario"]["field"] is None
    assert columns["Costo orario"]["not_used_reason"] == "HOURLY_RATE"


def test_the_backend_says_which_fields_are_required_and_the_page_never_does(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = inspection(api_client, env, "LABOR", "t.csv", labor_it_file())

    assert body["requirement_groups"] == [
        ["work_date"],
        ["actual_hours", "planned_hours"],  # at least one of
        ["labor_category", "role"],
    ]
    fixed_value = {field["key"]: field["constant"] for field in body["fields"]}
    assert fixed_value["work_date"] is None  # a date can never be "the same on every row"
    assert fixed_value["labor_category"]["choices"][0] == "HOUSEKEEPING"
    assert fixed_value["currency"]["default"] == "EUR"


def test_a_file_without_a_team_column_is_not_complete_until_a_value_is_chosen(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = labor_it_file(header=NO_TEAM)
    body = inspection(api_client, env, "LABOR", "t.csv", content)

    assert body["suggestion_complete"] is False


def test_a_hotel_bookings_export_is_read_with_its_own_headers_and_dates(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = inspection(api_client, env, "BOOKINGS", "esportazione.csv", bookings_it_file())
    columns = by_header(body)

    assert columns["Data arrivo"]["field"] == "check_in"
    assert columns["Data partenza"]["field"] == "check_out"
    assert columns["Canale"]["field"] == "channel"
    assert columns["Importo camera"]["field"] == "room_revenue"
    assert columns["Data arrivo"]["date_order"] == "DMY"  # 20/11 cannot be month 20
    assert columns["Data prenotazione"]["date_order"] == "AMBIGUOUS"  # 01/10: only a person knows
    assert columns["Importo camera"]["number_style"] == "COMMA"
    assert body["suggestion_complete"] is True


def test_a_file_already_in_ninfas_own_format_needs_no_matching(
    api_client: TestClient, env: SourcesEnv
) -> None:
    for domain, name, content in (
        ("BOOKINGS", "p.csv", booking_bytes()),
        ("LABOR", "l.csv", labor_bytes()),
    ):
        body = inspection(api_client, env, domain, name, content)

        assert body["already_canonical"] is True and body["suggestion_complete"] is True, domain
        assert all(c["level"] == "RECOGNIZED" for c in body["columns"] if c["field"]), domain


def test_an_excel_file_is_read_with_real_dates_and_numbers(
    api_client: TestClient, env: SourcesEnv
) -> None:
    from datetime import datetime

    content = xlsx_bytes(
        {"Turni": [["Giorno", "Ore turno", "Reparto"], [datetime(2026, 10, 26), 8, "Cucina"]]}
    )
    body = inspection(api_client, env, "LABOR", "turni.xlsx", content)
    columns = by_header(body)

    assert body["file_type"] == "XLSX" and body["sheet_name"] == "Turni"
    assert columns["Giorno"]["examples"] == ["2026-10-26"]
    assert columns["Ore turno"]["examples"] == ["8"]
    assert columns["Giorno"]["field"] == "work_date"


def test_an_excel_file_with_several_sheets_asks_which_one_and_then_reads_it(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = xlsx_bytes(
        {
            "Riepilogo": [["Totale"], [10]],
            "Turni": [["Giorno", "Ore turno", "Reparto"], ["26/10/2026", 8, "Cucina"]],
        }
    )

    first = inspection(api_client, env, "LABOR", "turni.xlsx", content)
    second = inspect(api_client, env, "LABOR", "turni.xlsx", content, sheet="Turni").json()

    assert first["problem"] == "SHEET_REQUIRED" and first["requires_sheet_selection"] is True
    assert sorted(first["sheet_names"]) == ["Riepilogo", "Turni"] and first["columns"] == []
    assert second["problem"] is None and second["sheet_name"] == "Turni"
    assert by_header(second)["Giorno"]["field"] == "work_date"


@pytest.mark.parametrize(
    ("name", "content", "problem"),
    [
        ("vuoto.csv", b"", "EMPTY_FILE"),
        ("spazi.csv", b"  \n \n", "EMPTY_FILE"),
        ("turni.xls", b"\xd0\xcf\x11\xe0 not a csv", "UNSUPPORTED_FILE"),
        ("turni.pdf", b"%PDF-1.4", "UNSUPPORTED_FILE"),
        ("macro.xlsm", b"PK\x03\x04", "UNSUPPORTED_FILE"),
        ("falso.csv", xlsx_bytes({"A": [["x"], [1]]}), "UNSUPPORTED_FILE"),  # a workbook as .csv
        ("rotto.xlsx", b"this is not a workbook", "UNREADABLE_FILE"),
        ("binario.csv", b"Giorno;Ore\n26/10/2026;\x00\x01\x02\n", "UNREADABLE_FILE"),
        ("utf16.csv", "Giorno;Ore\n".encode("utf-16"), "UNREADABLE_FILE"),
        ("doppie.csv", b"Giorno;Ore;Ore\n26/10/2026;8;7\n", "DUPLICATE_COLUMNS"),
    ],
)
def test_a_file_that_cannot_be_read_says_why_in_one_word(
    api_client: TestClient, env: SourcesEnv, name: str, content: bytes, problem: str
) -> None:
    body = inspection(api_client, env, "LABOR", name, content)

    assert body["problem"] == problem and body["columns"] == []


def test_a_file_with_too_many_columns_is_refused_not_read(
    api_client: TestClient, env: SourcesEnv
) -> None:
    header = ";".join(f"Colonna {n}" for n in range(201))
    body = inspection(api_client, env, "LABOR", "larga.csv", f"{header}\n".encode())

    assert body["problem"] == "FILE_TOO_LARGE"


def test_a_file_over_the_maximum_is_refused_with_413(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = inspect(api_client, env, "LABOR", "enorme.csv", b"x" * (MAX_FILE_BYTES + 1))

    assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_reading_a_file_writes_nothing_at_all(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    before = writes(db_session, env)

    for domain, content in (("LABOR", labor_it_file()), ("BOOKINGS", bookings_it_file())):
        inspection(api_client, env, domain, "x.csv", content)
        inspection(api_client, env, domain, "x.csv", content)

    assert writes(db_session, env) == before == (0, 0, 0, 0)
    assert card(api_client, env, "STAFF")["state"] == "NOT_CONFIGURED"


def test_costs_arrive_as_fatturapa_xml_and_have_no_columns_to_match(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = inspect(api_client, env, "COSTS", "fatture.csv", b"a;b\n1;2\n")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNSUPPORTED_DOMAIN"


# --- is this matching enough? -------------------------------------------------------------------


def test_the_backend_lists_what_is_still_missing_group_by_group(
    api_client: TestClient, env: SourcesEnv
) -> None:
    nothing = check_mapping(api_client, env, "LABOR", decision({"Giorno": None, "Note": None}))
    only_date = check_mapping(api_client, env, "LABOR", decision({"Giorno": "work_date"}))
    date_and_hours = check_mapping(
        api_client, env, "LABOR", decision({"Giorno": "work_date", "Ore": "planned_hours"})
    )
    complete = check_mapping(
        api_client,
        env,
        "LABOR",
        decision({"Giorno": "work_date", "Ore": "actual_hours", "Reparto": "role"}),
    )

    assert nothing["valid"] is False and len(nothing["missing"]) == 3
    assert only_date["missing"] == [["actual_hours", "planned_hours"], ["labor_category", "role"]]
    assert date_and_hours["missing"] == [["labor_category", "role"]]
    assert complete == {"valid": True, "missing": [], "problems": []}


def test_a_fixed_value_can_stand_in_for_a_column_the_file_does_not_have(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = check_mapping(
        api_client,
        env,
        "LABOR",
        decision(
            {"Giorno": "work_date", "Ore": "planned_hours"},
            constants={"labor_category": "KITCHEN"},
        ),
    )

    assert body["valid"] is True


@pytest.mark.parametrize(
    ("columns", "constants", "code", "fields"),
    [
        ({"A": "work_date", "B": "work_date"}, {}, "FIELD_USED_TWICE", ["work_date"]),
        ({"A": "inventata"}, {}, "UNKNOWN_FIELD", ["inventata"]),
        ({"A": "work_date"}, {"work_date": "2026-10-26"}, "CONSTANT_NOT_ALLOWED", ["work_date"]),
        (
            {"A": "labor_category"},
            {"labor_category": "KITCHEN"},
            "COLUMN_AND_VALUE",
            ["labor_category"],
        ),
        (
            {"A": "work_date", "B": "planned_hours"},
            {"labor_category": "NON-ESISTE"},
            "INVALID_CONSTANT",
            ["labor_category"],
        ),
    ],
)
def test_a_contradictory_matching_is_reported_with_one_stable_code(
    api_client: TestClient,
    env: SourcesEnv,
    columns: dict[str, str],
    constants: dict[str, str],
    code: str,
    fields: list[str],
) -> None:
    body = check_mapping(api_client, env, "LABOR", decision(columns, constants=constants))

    assert body["valid"] is False
    assert {"code": code, "fields": fields} in body["problems"]


def test_bookings_have_their_own_required_fields_and_fixed_values(
    api_client: TestClient, env: SourcesEnv
) -> None:
    columns = {
        "Arrivo": "check_in",
        "Partenza": "check_out",
        "Prenotata": "booked_at",
        "Id": "source_record_id",
        "Importo": "room_revenue",
    }
    without = check_mapping(api_client, env, "BOOKINGS", decision(columns))
    with_fixed = check_mapping(
        api_client,
        env,
        "BOOKINGS",
        decision(columns, constants={"rooms": 1, "status": "CONFIRMED", "channel": "Diretto"}),
    )

    assert without["missing"] == [["status"], ["rooms"], ["channel"]]
    assert with_fixed["valid"] is True
    bad_rooms = check_mapping(
        api_client,
        env,
        "BOOKINGS",
        decision(columns, constants={"rooms": 0, "status": "CONFIRMED", "channel": "Diretto"}),
    )
    assert bad_rooms["valid"] is False and bad_rooms["problems"][0]["code"] == "INVALID_CONSTANT"


# --- trying the whole file ----------------------------------------------------------------------


def test_the_brief_scenario_every_row_is_judged_and_shown_in_ninfas_own_form(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = validation(api_client, env, "LABOR", labor_it_file(), LABOR_IT_DECISION)

    assert body["status"] == "READY" and body["can_import"] is True
    assert (body["rows_total"], body["rows_valid"], body["rows_invalid"]) == (3, 3, 0)
    assert body["sample_fields"] == ["work_date", "labor_category", "planned_hours"]
    assert body["sample_rows"] == [
        ["2026-10-26", "FRONT_OFFICE", "8"],  # "Reception" read into NINFA's own category
        ["2026-10-27", "HOUSEKEEPING", "8"],
        ["2026-10-28", "KITCHEN", "8"],  # "Cucina"
    ]
    assert {"question": "DATE_ORDER", "proven": "DMY", "columns": ["Giorno"]} in body[
        "format_hints"
    ]


def test_trying_a_file_writes_nothing_and_needs_no_source(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    before = writes(db_session, env)

    validation(api_client, env, "LABOR", labor_it_file(), LABOR_IT_DECISION)
    validation(api_client, env, "BOOKINGS", bookings_it_file(), BOOKINGS_IT_DECISION)

    assert writes(db_session, env) == before == (0, 0, 0, 0)
    assert db_session.scalar(select(func.count()).select_from(LaborEntry)) == 0


def test_dates_that_could_be_read_two_ways_are_asked_not_guessed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = labor_it_file(days=("01/11/2026", "02/11/2026", "03/11/2026"))
    ambiguous = decision({"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"})

    asked = validation(api_client, env, "LABOR", content, ambiguous)
    day_first = validation(api_client, env, "LABOR", content, {**ambiguous, "date_order": "DMY"})
    month_first = validation(api_client, env, "LABOR", content, {**ambiguous, "date_order": "MDY"})

    assert asked["status"] == "NEEDS_CHOICE" and asked["rows_total"] == 0
    assert asked["format_hints"] == [
        {"question": "DATE_ORDER", "proven": None, "columns": ["Giorno"]}
    ]
    assert day_first["sample_rows"][0][0] == "2026-11-01"  # 1 November
    assert month_first["sample_rows"][0][0] == "2026-01-11"  # 11 January


def test_a_date_that_proves_the_order_is_applied_without_asking(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = labor_it_file(days=("25/10/2026", "01/11/2026", "02/11/2026"))

    body = validation(
        api_client,
        env,
        "LABOR",
        content,
        decision({"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"}),
    )

    assert body["status"] == "READY"  # 25/10 cannot be month 25: the whole column is day-first
    assert [row[0] for row in body["sample_rows"]] == ["2026-10-25", "2026-11-01", "2026-11-02"]


def test_amounts_written_with_a_comma_are_read_as_such(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = csv_bytes(
        [
            ["Giorno", "Ore turno", "Reparto", "Costo previsto"],
            ["26/10/2026", "7,5", "Reception", "1.234,50"],
            ["27/10/2026", "8", "Cucina", "98,00"],
        ],
        delimiter=";",
    )
    mapping = decision(
        {
            "Giorno": "work_date",
            "Ore turno": "planned_hours",
            "Reparto": "role",
            "Costo previsto": "planned_cost",
        },
        constants={"currency": "EUR"},
    )

    body = validation(api_client, env, "LABOR", content, mapping)

    assert body["status"] == "READY" and body["rows_invalid"] == 0
    assert body["sample_fields"] == ["work_date", "labor_category", "planned_hours", "planned_cost"]
    assert body["sample_rows"][0] == ["2026-10-26", "FRONT_OFFICE", "7.5", "1234.5"]
    hint = {
        "question": "DECIMAL_STYLE",
        "proven": "COMMA",
        "columns": ["Ore turno", "Costo previsto"],
    }
    assert hint in body["format_hints"]


def test_amounts_that_could_mean_a_thousand_or_one_and_a_bit_are_asked(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = csv_bytes(
        [["Giorno", "Ore turno", "Reparto"], ["26/10/2026", "1.500", "Cucina"]], delimiter=";"
    )
    mapping = decision({"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"})

    asked = validation(api_client, env, "LABOR", content, mapping)
    as_decimal = validation(
        api_client, env, "LABOR", content, {**mapping, "decimal_style": "POINT"}
    )

    assert asked["status"] == "NEEDS_CHOICE"
    assert {"question": "DECIMAL_STYLE", "proven": None, "columns": ["Ore turno"]} in asked[
        "format_hints"
    ]
    assert as_decimal["status"] == "READY" and as_decimal["sample_rows"][0][-1] == "1.5"


def test_a_column_that_writes_its_dates_in_more_than_one_way_is_refused(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = labor_it_file(days=("26/10/2026", "27-10-2026", "28/10/2026"))

    body = validation(
        api_client,
        env,
        "LABOR",
        content,
        decision(
            {"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"},
            date_order="DMY",
        ),
    )

    assert body["status"] == "BLOCKED" and body["problem"] == "FORMAT_UNCLEAR"
    assert body["check"]["problems"] == [{"code": "DATES_MIXED", "fields": ["work_date"]}]


def test_rows_that_cannot_be_imported_are_counted_and_the_import_is_not_offered(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = csv_bytes(
        [
            ["Giorno", "Ore turno", "Reparto"],
            ["26/10/2026", "8", "Cucina"],
            ["27/10/2026", "otto", "Cucina"],
            ["31/12/2026", "-3", "Cucina"],
        ],
        delimiter=";",
    )

    body = validation(
        api_client,
        env,
        "LABOR",
        content,
        decision(
            {"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"},
            date_order="DMY",
        ),
    )

    assert body["status"] == "READY" and body["can_import"] is False
    assert (body["rows_total"], body["rows_valid"], body["rows_invalid"]) == (3, 1, 2)
    assert {item["code"] for item in body["row_problems"]} == {"INVALID_NUMBER", "NEGATIVE_VALUE"}
    assert [row["row"] for row in body["invalid_rows"]] == [3, 4]  # the file's own row numbers
    assert body["invalid_rows"][0]["issues"] == [
        {"field": "planned_hours", "code": "INVALID_NUMBER"}
    ]
    assert body["sample_rows"] == [["2026-10-26", "KITCHEN", "8"]]


def test_a_matching_that_names_a_column_the_file_does_not_have_is_refused(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = validation(
        api_client,
        env,
        "LABOR",
        labor_it_file(),
        decision(
            {"Giorno": "work_date", "Ore turno": "planned_hours", "Fantasma": "role"},
            date_order="DMY",
        ),
    )

    assert body["status"] == "BLOCKED" and body["problem"] == "MAPPING_INCOMPLETE"
    assert body["check"]["problems"] == [{"code": "UNKNOWN_COLUMN", "fields": ["Fantasma"]}]


def test_an_incomplete_matching_says_what_is_missing_instead_of_importing_half(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = validation(api_client, env, "LABOR", labor_it_file(), decision({"Giorno": "work_date"}))

    assert body["status"] == "BLOCKED" and body["problem"] == "MAPPING_INCOMPLETE"
    assert body["check"]["missing"] == [
        ["actual_hours", "planned_hours"],
        ["labor_category", "role"],
    ]


def test_a_file_with_only_a_header_has_no_rows_to_import(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = csv_bytes([["Giorno", "Ore turno", "Reparto"]], delimiter=";")

    body = validation(
        api_client,
        env,
        "LABOR",
        content,
        decision({"Giorno": "work_date", "Ore turno": "planned_hours", "Reparto": "role"}),
    )

    assert body["status"] == "BLOCKED" and body["problem"] in {"NO_ROWS", "EMPTY_FILE"}


def test_there_is_nothing_saved_to_try_a_file_with_before_a_first_import(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = validation(api_client, env, "LABOR", labor_it_file(), None)

    assert body["status"] == "BLOCKED" and body["problem"] == "PROFILE_NOT_USABLE"


def test_too_many_rows_stop_the_check_instead_of_filling_memory(
    api_client: TestClient, env: SourcesEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(parsers, "MAX_ROWS", 2)

    body = validation(api_client, env, "LABOR", labor_it_file(), LABOR_IT_DECISION)

    assert body["status"] == "BLOCKED" and body["problem"] == "FILE_TOO_LARGE"


def test_a_bookings_file_is_judged_with_its_own_rules_and_statuses(
    api_client: TestClient, env: SourcesEnv
) -> None:
    unknown_status = validation(
        api_client, env, "BOOKINGS", bookings_it_file(status="Provvisoria"), BOOKINGS_IT_DECISION
    )

    assert unknown_status["status"] == "READY" and unknown_status["can_import"] is False
    assert unknown_status["rows_invalid"] == 2
    assert unknown_status["row_problems"][0]["field"] == "status"
    fixed_status = validation(
        api_client,
        env,
        "BOOKINGS",
        bookings_it_file(status="Provvisoria"),
        decision(
            {
                "N. prenotazione": "source_record_id",
                "Data prenotazione": "booked_at",
                "Data arrivo": "check_in",
                "Data partenza": "check_out",
                "Stato": None,
                "Camere": "rooms",
                "Importo camera": "room_revenue",
                "Canale": "channel",
            },
            constants={"status": "CONFIRMED"},
            date_order="DMY",
        ),
    )
    assert fixed_status["can_import"] is True


def test_the_dry_run_of_a_file_already_imported_says_so(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = bookings_it_file()
    assert import_mapped(
        api_client, env, "BOOKINGS", "p.csv", content, BOOKINGS_IT_DECISION
    ).json()["succeeded"]

    body = validation(
        api_client, env, "BOOKINGS", content, BOOKINGS_IT_DECISION, name="altro-nome.csv"
    )

    assert body["already_imported"] is True


# --- the new routes are as closed as the rest ---------------------------------------------------


def test_every_smart_import_route_answers_401_without_a_session(
    api_client: TestClient, factory: BookingFactory
) -> None:
    prop = factory.property(factory.workspace())
    base = f"/api/v1/properties/{prop.id}/data-sources"
    some = UUID(int=1)
    calls = [
        ("post", f"{base}/import-inspection?domain=LABOR&filename=a.csv"),
        ("post", f"{base}/import-mapping-check"),
        ("post", f"{base}/import-validation"),
        ("post", f"{base}/imports/mapped"),
        ("get", f"{base}/{some}/import-configuration"),
        ("delete", f"{base}/{some}/import-configuration"),
    ]
    for method, url in calls:
        assert getattr(api_client, method)(url).status_code == 401, (method, url)


def test_a_property_of_another_workspace_is_the_same_404_as_a_missing_one(
    api_client: TestClient, factory: BookingFactory, env: SourcesEnv
) -> None:
    foreign = factory.property(factory.workspace())
    missing = UUID(int=2)
    for property_id in (foreign.id, missing):
        base = f"/api/v1/properties/{property_id}/data-sources"
        responses = [
            api_client.post(
                f"{base}/import-inspection?domain=LABOR&filename=a.csv", content=labor_it_file()
            ),
            post_json(
                api_client, f"{base}/import-mapping-check", {"domain": "LABOR", "mapping": {}}
            ),
            post_json(
                api_client,
                f"{base}/import-validation",
                {"domain": "LABOR", "filename": "a.csv", "file_base64": b64(b"x"), "mapping": None},
            ),
            api_client.get(f"{base}/{UUID(int=1)}/import-configuration"),
        ]
        assert {r.status_code for r in responses} == {404}, property_id
        assert {r.json()["error"]["code"] for r in responses} == {"PROPERTY_NOT_FOUND"}


def test_a_request_that_is_not_what_the_page_sends_is_refused_before_anything_is_read(
    api_client: TestClient, env: SourcesEnv
) -> None:
    url = f"{env.base}/import-validation"
    headers = {"Content-Type": "application/json"}
    valid = {"domain": "LABOR", "filename": "a.csv", "file_base64": b64(b"x"), "mapping": None}
    cases = {
        "not json": b"{not json",
        "an array": b"[]",
        "missing file": json.dumps({"domain": "LABOR", "filename": "a.csv"}).encode(),
        "unknown field": json.dumps({**valid, "extra": 1}).encode(),
        "unknown domain": json.dumps({**valid, "domain": "NOPE"}).encode(),
        "not base64": json.dumps({**valid, "file_base64": "***not base64***"}).encode(),
        "bad mapping": json.dumps({**valid, "mapping": {"columns": "no"}}).encode(),
        "too many columns": json.dumps(
            {
                **valid,
                "mapping": {"columns": [{"header": f"c{n}", "field": None} for n in range(201)]},
            }
        ).encode(),
    }

    for label, body in cases.items():
        response = api_client.post(url, content=body, headers=headers)
        assert response.status_code == 422, (label, response.text)
        assert response.json()["error"]["code"] in {"INVALID_IMPORT_REQUEST", "validation_error"}, (
            label
        )


def test_a_body_over_the_maximum_is_stopped_while_it_is_read(
    api_client: TestClient, env: SourcesEnv
) -> None:
    from app.api.v1.sources.schemas import MAX_JSON_BODY_BYTES

    response = api_client.post(
        f"{env.base}/import-validation",
        content=b"x" * (MAX_JSON_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_a_file_over_the_maximum_inside_the_body_is_refused_with_413(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    big = b"A;B\n" + b"1;2\n" * (MAX_FILE_BYTES // 4 + 10)

    response = import_mapped(api_client, env, "LABOR", "grande.csv", big, LABOR_IT_DECISION)

    assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert writes(db_session, env) == (0, 0, 0, 0)


def test_the_old_routes_still_work_next_to_the_new_ones(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = raw(api_client, env.imports_url("BOOKINGS", "prenotazioni.csv"), booking_bytes())

    assert response.status_code == 200 and response.json()["succeeded"] is True
    assert "configuration_saved" not in response.json()  # the first route's answer is unchanged
