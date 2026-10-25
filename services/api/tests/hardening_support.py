"""Small documents and a database-free understanding service, for the deterministic hardening tests
of Smart Import V3 (`test_smart_import_hardening.py`, `test_personal_data_guard.py`).

Everything is invented: names are plausible and combined at random, e-mail addresses are on
`example.org`, telephone numbers start with a block that is not assigned, tax codes use a month
letter that does not exist. The documents are REAL bytes (an .xlsx written with openpyxl) read by
the same code the `/import-understanding` route calls, so a test here says what the person would
be shown - without a database, a model, or the network.
"""

import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from openpyxl import Workbook

from app.api.v1.sources.router import _inspection_response
from app.core.tenant import TenantContext
from app.modules.data_sources.mapping_types import ColumnInfo, FileInspection
from app.modules.data_sources.smart_import import SmartImportService
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.ingestion.models import DataSourceDomain

LABOR = DataSourceDomain.LABOR
BOOKINGS = DataSourceDomain.BOOKINGS
COSTS = DataSourceDomain.COSTS

MONDAY = date(2026, 10, 19)
PEOPLE = [
    "Giulia Ferretti",
    "Marco Rinaldi",
    "Elena Orlandi",
    "Davide Dallari",
    "Chiara Carrara",
    "Matteo Olivieri",
]
DEPARTMENTS = ["Reception", "Housekeeping", "Cucina", "Manutenzione", "Reception", "Housekeeping"]
CHANNELS = ["Booking.com", "Expedia", "Diretto", "Airbnb", "Telefono", "Sito web"]
SUPPLIERS = [
    "Elettra Energia S.p.A.",
    "Lavanderia Marinelli S.n.c.",
    "Panificio Delle Rose S.r.l.",
    "Termoidraulica Sereni S.r.l.",
]


def xlsx(
    rows: Iterable[Sequence[Any]], *, merges: Sequence[str] = (), sheet: str = "Foglio1"
) -> bytes:
    """A workbook with one sheet holding these rows (merged ranges as "E1:G1")."""
    book = Workbook()
    worksheet = book.active
    assert worksheet is not None
    worksheet.title = sheet
    for row in rows:
        worksheet.append(list(row))
    for merged in merges:
        worksheet.merge_cells(merged)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


_SHORT_WEEKDAYS = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
_LONG_WEEKDAYS = (
    "Lunedì",
    "Martedì",
    "Mercoledì",
    "Giovedì",
    "Venerdì",
    "Sabato",
    "Domenica",
)


def with_weekday(moment: date | datetime, *, long: bool = False) -> str:
    """A day written the way a calendar export does: "gio 29/10/2026"."""
    names = _LONG_WEEKDAYS if long else _SHORT_WEEKDAYS
    return f"{names[moment.weekday()]} {moment:%d/%m/%Y}"


def service() -> UnderstandingService:
    """The real understanding service: no database, no source, and no assistant."""
    tenant = TenantContext(UUID(int=1))
    return UnderstandingService(None, tenant, SmartImportService(None, tenant), None)  # type: ignore[arg-type]


def understand(
    domain: DataSourceDomain,
    content: bytes,
    *,
    filename: str = "file.xlsx",
    **answers: Any,
) -> FileInspection:
    """What the person is shown for a first upload (or after the answers given)."""
    return service().understand(
        domain,
        filename,
        content,
        UnderstandAnswers(**answers),
        False,
        None,
        False,
        currency="EUR",
    )


def by_header(inspection: FileInspection) -> dict[str, ColumnInfo]:
    return {column.header: column for column in inspection.columns}


def field_of(inspection: FileInspection, header: str) -> str | None:
    return by_header(inspection)[header].field


def question_kinds(inspection: FileInspection) -> list[str]:
    assert inspection.understanding is not None
    return [question.kind.value for question in inspection.understanding.questions]


def level_of(inspection: FileInspection) -> str:
    assert inspection.understanding is not None
    return inspection.understanding.level.value


def asked_columns(inspection: FileInspection) -> list[str | None]:
    assert inspection.understanding is not None
    return [question.column for question in inspection.understanding.questions]


def payload_of(inspection: FileInspection) -> str:
    """Exactly what the API would send to the browser for this answer."""
    return _inspection_response(inspection).model_dump_json()


# --- staff ---------------------------------------------------------------------------------------


def staff(
    header: Sequence[str],
    *,
    days: int = 3,
    people: Sequence[str] = PEOPLE,
    planned: Any = 8,
    worked: Any = 7.5,
) -> list[list[Any]]:
    """A header and one row per person per day: date, person, department, then hours."""
    rows: list[list[Any]] = [list(header)]
    for offset in range(days):
        for person, department in zip(people, DEPARTMENTS, strict=False):
            day = datetime.combine(MONDAY + timedelta(days=offset), datetime.min.time())
            rows.append([day, person, department, planned, worked])
    return rows


# --- bookings ------------------------------------------------------------------------------------


def booking_row(index: int) -> list[Any]:
    arrival = datetime(2026, 11, 1) + timedelta(days=index)
    return [
        f"BK-{10000 + index}",
        datetime(2026, 10, 1, 10, index % 60),
        arrival,
        arrival + timedelta(days=1 + index % 3),
        CHANNELS[index % len(CHANNELS)],
        100 + 10 * index,
        "Confermata",
        1,
    ]


BOOKING_HEADER = [
    "Codice prenotazione",
    "Data prenotazione",
    "Arrivo",
    "Partenza",
    "Canale",
    "Importo camere",
    "Stato",
    "Camere",
]


def bookings(count: int = 24, header: Sequence[str] = BOOKING_HEADER) -> list[list[Any]]:
    return [list(header), *[booking_row(i) for i in range(count)]]


# --- costs ---------------------------------------------------------------------------------------


def cost_row(index: int, *amounts: Any) -> list[Any]:
    return [
        datetime(2026, 10, 1) + timedelta(days=3 * index),
        f"FT/2026/{100 + index:04d}",
        SUPPLIERS[index % len(SUPPLIERS)],
        f"Fornitura {index + 1} - 10/2026",
        *amounts,
    ]


COST_HEADER = ["Data", "N. documento", "Fornitore", "Descrizione"]


def costs(
    amount_headers: Sequence[str],
    amounts: Sequence[Sequence[Any]],
    *,
    header: Sequence[str] = COST_HEADER,
) -> list[list[Any]]:
    """A register: the usual four columns, then these amount columns with these values per row."""
    return [
        [*header, *amount_headers],
        *[cost_row(i, *values) for i, values in enumerate(amounts)],
    ]
