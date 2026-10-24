"""Shared helpers for the Smart Import tests (the hotel's OWN CSV / Excel file, columns matched).

Every file here is REAL bytes, written the way a hotel actually writes them: Italian headers,
`;` as the delimiter, a BOM, day-first dates, a comma as the decimal mark, names of people and an
hourly rate that NINFA never reads. They go through the real readers and the real import services.
"""

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import BookingMappingProfile
from app.modules.ingestion.models import DataSourceDomain, ImportFile
from app.modules.labor.models import LaborMappingProfile
from tests.booking_support import csv_bytes, xlsx_bytes
from tests.data_sources_support import LABOR_DAY, SourcesEnv, jobs_of, sources_of

__all__ = [
    "LABOR_DAY",
    "b64",
    "by_header",
    "check_mapping",
    "bookings_it_file",
    "csv_bytes",
    "decision",
    "dry_run",
    "forget_url",
    "import_mapped",
    "inspect",
    "inspection",
    "labor_it_file",
    "understand",
    "post_json",
    "profiles_of",
    "validation",
    "writes",
    "xlsx_bytes",
]

# The scenario of the product brief: a shifts file with a person's name and an hourly rate.
LABOR_IT_HEADER = ["Giorno", "Nome dipendente", "Ore turno", "Costo orario", "Reparto"]
BOOKINGS_IT_HEADER = [
    "N. prenotazione",
    "Data prenotazione",
    "Data arrivo",
    "Data partenza",
    "Stato",
    "Camere",
    "Importo camera",
    "Canale",
]


def labor_it_file(
    *,
    days: Sequence[str] = ("26/10/2026", "27/10/2026", "28/10/2026"),
    delimiter: str = ";",
    bom: bool = True,
    hours: str = "8",
    header: Sequence[str] = LABOR_IT_HEADER,
) -> bytes:
    """A staff-shifts file as an Italian hotel keeps it: a day, a person, hours, a rate, a team."""
    rows: list[list[str]] = [list(header)]
    teams = ["Reception", "Housekeeping", "Cucina"]
    for index, day in enumerate(days):
        rows.append([day, f"Persona {index + 1}", hours, "14,50", teams[index % len(teams)]])
    return csv_bytes(rows, delimiter=delimiter, bom=bom)


def bookings_it_file(
    *,
    arrivals: Sequence[str] = ("12/11/2026", "20/11/2026"),
    delimiter: str = ";",
    bom: bool = True,
    status: str = "Confermata",
    amount: str = "150,00",
) -> bytes:
    """A bookings export as an Italian PMS writes it (Italian headers, day-first dates)."""
    rows: list[list[str]] = [list(BOOKINGS_IT_HEADER)]
    for index, arrival in enumerate(arrivals, start=1):
        day = int(arrival[:2])
        departure = f"{day + 2:02d}{arrival[2:]}"
        rows.append(
            [
                f"IT-{index:04d}",
                "01/10/2026",
                arrival,
                departure,
                status,
                "1",
                amount,
                "Booking.com",
            ]
        )
    return csv_bytes(rows, delimiter=delimiter, bom=bom)


# --- the person's decision, as the page sends it ------------------------------------------------


def decision(
    columns: Mapping[str, str | None],
    *,
    constants: Mapping[str, str | int] | None = None,
    date_order: str | None = None,
    decimal_style: str | None = None,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """`columns` maps a header of the file to what it means (None: ignore this column)."""
    body: dict[str, Any] = {
        "columns": [{"header": header, "field": field} for header, field in columns.items()],
        "constants": dict(constants or {}),
    }
    if date_order is not None:
        body["date_order"] = date_order
    if decimal_style is not None:
        body["decimal_style"] = decimal_style
    if sheet_name is not None:
        body["sheet_name"] = sheet_name
    return body


# The scenario B decision: day, hours of the shift, the team; the person and the rate are ignored.
LABOR_IT_DECISION = decision(
    {
        "Giorno": "work_date",
        "Nome dipendente": None,
        "Ore turno": "planned_hours",
        "Costo orario": None,
        "Reparto": "role",
    },
    date_order="DMY",
)

BOOKINGS_IT_DECISION = decision(
    {
        "N. prenotazione": "source_record_id",
        "Data prenotazione": "booked_at",
        "Data arrivo": "check_in",
        "Data partenza": "check_out",
        "Stato": "status",
        "Camere": "rooms",
        "Importo camera": "room_revenue",
        "Canale": "channel",
    },
    date_order="DMY",
)


# --- the routes ---------------------------------------------------------------------------------


def b64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def post_json(client: TestClient, url: str, payload: Mapping[str, Any]) -> Any:
    return client.post(
        url, content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )


def inspect(
    client: TestClient,
    env: SourcesEnv,
    domain: str,
    filename: str,
    content: bytes,
    sheet: str | None = None,
) -> Any:
    url = f"{env.base}/import-inspection?domain={domain}&filename={filename}"
    if sheet is not None:
        url += f"&sheet_name={sheet}"
    return client.post(url, content=content, headers={"Content-Type": "application/octet-stream"})


def understand(
    client: TestClient,
    env: SourcesEnv,
    domain: str,
    filename: str,
    content: bytes,
    answers: Mapping[str, Any] | None = None,
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    """What NINFA understands of a whole document (Smart Import V3)."""
    response = post_json(
        client,
        f"{env.base}/import-understanding",
        {
            "domain": domain,
            "filename": filename,
            "file_base64": b64(content),
            "confirmed_domain": confirmed,
            "answers": dict(answers or {}),
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def dry_run(
    client: TestClient,
    env: SourcesEnv,
    domain: str,
    filename: str,
    content: bytes,
    mapping: Mapping[str, Any] | None,
) -> Any:
    return post_json(
        client,
        f"{env.base}/import-validation",
        {"domain": domain, "filename": filename, "file_base64": b64(content), "mapping": mapping},
    )


def import_mapped(
    client: TestClient,
    env: SourcesEnv,
    domain: str,
    filename: str,
    content: bytes,
    mapping: Mapping[str, Any] | None,
    *,
    save: bool = True,
    snapshot: str | None = None,
) -> Any:
    payload: dict[str, Any] = {
        "domain": domain,
        "filename": filename,
        "file_base64": b64(content),
        "mapping": mapping,
        "save_configuration": save,
    }
    if domain == "LABOR":
        payload["snapshot_local_date"] = snapshot or LABOR_DAY
    return post_json(client, f"{env.base}/imports/mapped", payload)


def forget_url(env: SourcesEnv, data_source_id: object) -> str:
    return f"{env.base}/{data_source_id}/import-configuration"


# --- answers, read the way the tests need them --------------------------------------------------


def inspection(client: TestClient, env: SourcesEnv, domain: str, name: str, data: bytes) -> Any:
    response = inspect(client, env, domain, name, data)
    assert response.status_code == 200, response.text
    return response.json()


def by_header(body: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {column["header"]: column for column in body["columns"]}


def check_mapping(
    client: TestClient, env: SourcesEnv, domain: str, mapping: Mapping[str, Any]
) -> Any:
    response = post_json(
        client, f"{env.base}/import-mapping-check", {"domain": domain, "mapping": mapping}
    )
    assert response.status_code == 200, response.text
    return response.json()


def validation(
    client: TestClient,
    env: SourcesEnv,
    domain: str,
    content: bytes,
    mapping: Mapping[str, Any] | None,
    name: str = "f.csv",
) -> Any:
    response = dry_run(client, env, domain, name, content, mapping)
    assert response.status_code == 200, response.text
    return response.json()


def profiles_of(db_session: Session, env: SourcesEnv, model: Any) -> list[Any]:
    """The saved configurations of the property (a labor or a booking mapping profile)."""
    return list(
        db_session.scalars(
            select(model).where(
                model.workspace_id == env.workspace.id, model.property_id == env.property.id
            )
        )
    )


def writes(db_session: Session, env: SourcesEnv) -> tuple[int, int, int, int]:
    """Everything Smart Import could write: sources, jobs, files and saved configurations."""
    sources = sum(len(sources_of(db_session, env, domain)) for domain in DataSourceDomain)
    return (
        sources,
        len(jobs_of(db_session, env)),
        int(db_session.scalar(select(func.count()).select_from(ImportFile)) or 0),
        len(profiles_of(db_session, env, LaborMappingProfile))
        + len(profiles_of(db_session, env, BookingMappingProfile)),
    )
