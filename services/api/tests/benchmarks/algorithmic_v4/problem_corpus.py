"""The V4 problem corpus: files whose headers are plausible and NOT the importers' own names.

WHY IT EXISTS. The official corpus and the unseen-file corpus were written for the V3 engine; they
say how often V3 reads what it was shaped to read. A hotel's own export is not shaped for NINFA: a
database column is `reservation_code`, a PMS says `RESV_STATUS`, a gestionale `Nr. Pratica`, a
person
types `Arival Date`. This corpus draws those, so that the question "what does an algorithmic reader
add?" is asked of files the V3 vocabulary was not fitted to.

HOW IT WAS WRITTEN (so the measurement can be trusted):

* written BEFORE the V4 engine existed, from what exports, PMSs and spreadsheets really use; frozen
at
  its first run against V3 and not edited after seeing a V4 result (a bug of the corpus is the only
  reason to touch it, and is recorded in the report);
* NO word of the benchmark's held-out vocabulary (`openai_intelligence.HELD_OUT`) is used, and none
  of the vocabulary phrases of V4 was taken from this file (`test_algorithmic_vocabulary` checks the
  first, the order of work the second);
* the truth is written by the recipe NEXT TO the file (`Col.field`), never read from Smart Import.

KINDS (every document carries its kind as a tag):

    plain        a name a person reads at once, in a style no importer knows verbatim
    camel        CheckInDate, BookingStatus, RoomTotal: words glued by capitals
    glued        checkindate, bookingstatus: words glued with nothing
    typo         Arival Date, Reservaton Code: a spelling mistake
    qualifier    "Room Revenue (EUR)", "Status *": a unit or a mark after the name
    unnamed      the header says nothing ("Campo 3"): only the values can name the column
    personal     a plain-named file with guest names and addresses that must never be read

A `READY` truth is a file a careful person would import without asking; for a typo the careful
person
reads through it, so a confirmation question on it is tolerated (not penalised, not required). An
`unnamed` file is never READY: asking, or matching by hand, are the right outcomes, and a confident
reading would be false automation.
"""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col, flat_document
from tests.benchmarks.smart_import_v3.kit import Built, structure_of
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.pool import email_of, guest, guest_name, seeded
from tests.benchmarks.universal_understanding_v2.common import (
    date_cell,
    decimal_of,
    money_cell,
    order_of,
)
from tests.benchmarks.universal_understanding_v2.gen_bookings import Stay, stays

SEED = "smart-import-v4-problem-corpus-v1"
UNNAMED = ("Campo 1", "Campo 2", "Campo 3", "Campo 4", "Campo 5", "Dato A", "Dato B", "Dato C")


@dataclass(frozen=True, slots=True)
class Look:
    """How the VALUES of a document are written."""

    lang: str  # "it" | "en": the words of statuses and channels
    dates: str  # date style (common.date_cell)
    money: str  # money style (common.money_cell)
    csv: dict[str, Any] | None  # None: an .xlsx


LOOKS = {
    "xlsx": Look("it", "xl", "num", None),
    "csv_it": Look("it", "it", "it_plain", {"delimiter": ";", "decimal": ",", "dates": "it"}),
    "csv_iso": Look("en", "iso", "point", {"delimiter": ",", "decimal": ".", "dates": "iso"}),
    "csv_tab": Look("en", "iso", "point", {"delimiter": "\t", "decimal": ".", "dates": "iso"}),
}


def _rng(case_id: str) -> random.Random:
    return seeded(case_id, seed=SEED)


def _formats(look: Look) -> dict[str, Any]:
    return {"date_order": order_of(look.dates), "decimal": decimal_of(look.money)}


# ==================================================================================================
# bookings
# ==================================================================================================

BOOKING_FIELDS = (
    "source_record_id",
    "booked_at",
    "check_in",
    "check_out",
    "status",
    "rooms",
    "room_revenue",
    "channel",
)

# style -> (kind, field -> header)
BOOKING_STYLES: dict[str, tuple[str, dict[str, str]]] = {
    "snake": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "reservation_code",
                    "booking_date",
                    "arrival_date",
                    "departure_date",
                    "booking_status",
                    "rooms",
                    "room_total",
                    "sales_channel",
                ),
                strict=True,
            )
        ),
    ),
    "opera": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "CONFIRMATION_NO",
                    "INSERT_DATE",
                    "ARRIVAL",
                    "DEPARTURE",
                    "RESV_STATUS",
                    "NO_OF_ROOMS",
                    "ROOM_REVENUE",
                    "SOURCE_CODE",
                ),
                strict=True,
            )
        ),
    ),
    "gestionale": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Nr. Pratica",
                    "Data Prenotazione",
                    "Data Arrivo",
                    "Data Partenza",
                    "Stato",
                    "N. Camere",
                    "Importo Camere",
                    "Canale",
                ),
                strict=True,
            )
        ),
    ),
    "informal_it": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Codice prenotazione",
                    "Prenotata il",
                    "Dal giorno",
                    "Al giorno",
                    "Stato della prenotazione",
                    "Numero camere",
                    "Totale camera",
                    "Provenienza prenotazione",
                ),
                strict=True,
            )
        ),
    ),
    "friendly_en": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Reservation Number",
                    "Date Booked",
                    "Arrival Date",
                    "Departure Date",
                    "Reservation Status",
                    "Number of Rooms",
                    "Room Total",
                    "Booking Source",
                ),
                strict=True,
            )
        ),
    ),
    "abbrev": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Res No",
                    "Bkd Date",
                    "Arr",
                    "Dep",
                    "Status",
                    "Rms",
                    "Room Rev",
                    "Channel",
                ),
                strict=True,
            )
        ),
    ),
    "mixed": (
        "plain",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Booking ID",
                    "Data prenotazione",
                    "Check-in",
                    "Check-out",
                    "Stato",
                    "Rooms",
                    "Ricavo camere",
                    "Channel",
                ),
                strict=True,
            )
        ),
    ),
    "camel": (
        "camel",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "ReservationId",
                    "BookingCreatedAt",
                    "CheckInDate",
                    "CheckOutDate",
                    "BookingStatus",
                    "NumberOfRooms",
                    "RoomRevenue",
                    "BookingChannel",
                ),
                strict=True,
            )
        ),
    ),
    "camel_short": (
        "camel",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "ResCode",
                    "BookedOn",
                    "ArrivalDate",
                    "DepartureDate",
                    "Status",
                    "RoomCount",
                    "RoomTotal",
                    "Channel",
                ),
                strict=True,
            )
        ),
    ),
    "glued": (
        "glued",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "reservationid",
                    "bookingdate",
                    "checkindate",
                    "checkoutdate",
                    "bookingstatus",
                    "roomcount",
                    "roomrevenue",
                    "channelname",
                ),
                strict=True,
            )
        ),
    ),
    "glued_it": (
        "glued",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "codiceprenotazione",
                    "dataprenotazione",
                    "dataarrivo",
                    "datapartenza",
                    "statoprenotazione",
                    "numerocamere",
                    "ricavocamere",
                    "canaledivendita",
                ),
                strict=True,
            )
        ),
    ),
    "typo": (
        "typo",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Reservaton Code",
                    "Booking Dat",
                    "Arival Date",
                    "Departur Date",
                    "Booking Statuss",
                    "Number of Roms",
                    "Room Revenu",
                    "Channle",
                ),
                strict=True,
            )
        ),
    ),
    "qualifier": (
        "qualifier",
        dict(
            zip(
                BOOKING_FIELDS,
                (
                    "Reservation Code *",
                    "Booking Date (dd/mm/yyyy)",
                    "Check-in (date)",
                    "Check-out (date)",
                    "Status (PMS)",
                    "Rooms #",
                    "Room Revenue (EUR)",
                    "Channel (OTA)",
                ),
                strict=True,
            )
        ),
    ),
}


def _booking_cols(headers: dict[str, str], look: Look) -> list[Col]:
    lang = look.lang
    return [
        Col(headers["source_record_id"], lambda s: s.ref, "source_record_id"),
        Col(headers["booked_at"], lambda s: date_cell(s.booked.date(), look.dates), "booked_at"),
        Col(headers["check_in"], lambda s: date_cell(s.arrival, look.dates), "check_in"),
        Col(headers["check_out"], lambda s: date_cell(s.departure, look.dates), "check_out"),
        Col(headers["status"], lambda s: s.status_label(lang), "status"),
        Col(headers["rooms"], lambda s: s.rooms, "rooms"),
        Col(headers["room_revenue"], lambda s: money_cell(s.revenue, look.money), "room_revenue"),
        Col(headers["channel"], lambda s: s.channel_label(lang), "channel"),
    ]


def _status_labels(items: Sequence[Stay], lang: str) -> dict[str, dict[str, str]]:
    return {"status_mapping": {s.status_label(lang): s.status for s in items}}


def _booking_doc(
    case_id: str,
    style: str,
    look_name: str,
    *,
    extras: Sequence[str] = (),
    override: Mapping[str, str] | None = None,
) -> Doc:
    kind, headers = BOOKING_STYLES[style]
    if override:
        kind, headers = "typo_one", {**headers, **override}
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = stays(
        rng, rng.randint(14, 26), statuses=("CONFIRMED", "CONFIRMED", "CANCELLED", "NO_SHOW")
    )
    cols = _booking_cols(headers, look)
    if "personal" in extras:
        cols += [
            Col("Guest name", lambda s: guest_name(s.guest), pii=True),
            Col("Guest email", lambda s: email_of(*guest(s.guest)), pii=True),
        ]
    if "junk" in extras:
        cols += [Col("Operatore", lambda s: "front" + str(s.guest % 3 + 1))]
    outcome = "READY"
    tolerated = ("COLUMN_MEANING",) if kind == "typo" else ()
    built = flat_document(
        "bookings",
        f"{style}.csv" if look.csv else f"{style}.xlsx",
        cols,
        items,
        outcome=outcome,
        csv=look.csv,
        labels=_status_labels(items, look.lang),
        tolerated=tolerated,
        sheet_title="Prenotazioni",
        note=f"V4 problem corpus - bookings, style {style} ({kind})",
        **_formats(look),
    )
    return _doc(case_id, "bookings", built, ("bookings", kind, f"style:{style}", *extras))


def _unnamed_booking_doc(case_id: str, hidden: Sequence[str], look_name: str) -> Doc:
    """The headers of the columns named in `hidden` say nothing; the rest are plain."""
    _kind, headers = BOOKING_STYLES["snake"]
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = stays(
        rng, rng.randint(14, 26), statuses=("CONFIRMED", "CONFIRMED", "CANCELLED", "NO_SHOW")
    )
    names = dict(headers)
    taken = iter(UNNAMED)
    for field in hidden:
        names[field] = next(taken)
    cols = []
    for col in _booking_cols(names, look):
        # a column whose header says nothing is only a reading a person may confirm
        cols.append(
            Col(col.header, col.cell, col.field, ambiguous=col.field in hidden)
            if col.field in hidden
            else col
        )
    built = flat_document(
        "bookings",
        "export.csv" if look.csv else "export.xlsx",
        cols,
        items,
        outcome="NOT_AUTOMATIC",
        csv=look.csv,
        labels=_status_labels(items, look.lang),
        note=f"V4 problem corpus - bookings, unnamed columns {','.join(hidden)}",
        **_formats(look),
    )
    return _doc(
        case_id, "bookings", built, ("bookings", "unnamed", *(f"hidden:{h}" for h in hidden))
    )


# ==================================================================================================
# staff
# ==================================================================================================

DEPARTMENTS = ("Reception", "Housekeeping", "Cucina", "Sala", "Bar", "Manutenzione")


@dataclass(frozen=True, slots=True)
class Shift:
    day: date
    department: str
    planned: float
    actual: float
    person: int


def _shifts(rng: random.Random, count: int) -> list[Shift]:
    start = date(2026, 10, 5)
    out = []
    for index in range(count):
        planned = float(rng.choice((4, 5, 6, 6.5, 7, 8, 8)))
        out.append(
            Shift(
                start + timedelta(days=index // 6),
                DEPARTMENTS[index % len(DEPARTMENTS)],
                planned,
                max(0.0, planned + rng.choice((-1.0, -0.5, 0.0, 0.0, 0.5, 1.0))),
                index % 14,
            )
        )
    return out


LABOR_FIELDS = ("work_date", "department", "planned_hours", "actual_hours")
LABOR_STYLES: dict[str, tuple[str, dict[str, str]]] = {
    "snake": (
        "plain",
        dict(
            zip(
                LABOR_FIELDS,
                ("shift_date", "department", "planned_hours", "worked_hours"),
                strict=True,
            )
        ),
    ),
    "italiano": (
        "plain",
        dict(
            zip(
                LABOR_FIELDS, ("Data Turno", "Reparto", "Ore Previste", "Ore Lavorate"), strict=True
            )
        ),
    ),
    "mixed": (
        "plain",
        dict(
            zip(
                LABOR_FIELDS,
                ("Giorno", "Reparto/Mansione", "Ore pianificate", "Ore effettive"),
                strict=True,
            )
        ),
    ),
    "sched": (
        "plain",
        dict(zip(LABOR_FIELDS, ("Date", "Dept", "Scheduled Hours", "Hours Worked"), strict=True)),
    ),
    "camel": (
        "camel",
        dict(
            zip(
                LABOR_FIELDS,
                ("WorkDate", "DepartmentName", "PlannedHours", "ActualHours"),
                strict=True,
            )
        ),
    ),
    "glued": (
        "glued",
        dict(
            zip(
                LABOR_FIELDS,
                ("workdate", "departmentname", "plannedhours", "actualhours"),
                strict=True,
            )
        ),
    ),
    "typo": (
        "typo",
        dict(
            zip(
                LABOR_FIELDS, ("Shift Dat", "Departmnt", "Planed Hours", "Actual Hous"), strict=True
            )
        ),
    ),
    "qualifier": (
        "qualifier",
        dict(
            zip(
                LABOR_FIELDS,
                ("Date (dd/mm/yyyy)", "Department *", "Planned Hours (h)", "Actual Hours (h)"),
                strict=True,
            )
        ),
    ),
}


def _labor_cols(headers: dict[str, str], look: Look) -> list[Col]:
    return [
        Col(headers["work_date"], lambda s: date_cell(s.day, look.dates), "work_date"),
        Col(headers["department"], lambda s: s.department, "department"),
        Col(headers["planned_hours"], lambda s: s.planned, "planned_hours"),
        Col(headers["actual_hours"], lambda s: s.actual, "actual_hours"),
    ]


def _labor_doc(
    case_id: str,
    style: str,
    look_name: str,
    *,
    personal: bool = False,
    override: Mapping[str, str] | None = None,
) -> Doc:
    kind, headers = LABOR_STYLES[style]
    if override:
        kind, headers = "typo_one", {**headers, **override}
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = _shifts(rng, rng.randint(24, 48))
    cols = _labor_cols(headers, look)
    if personal:
        cols.append(Col("Dipendente", lambda s: guest_name(s.person), pii=True))
    built = flat_document(
        "labor",
        f"{style}.csv" if look.csv else f"{style}.xlsx",
        cols,
        items,
        csv=look.csv,
        tolerated=("COLUMN_MEANING",) if kind == "typo" else (),
        sheet_title="Turni",
        note=f"V4 problem corpus - staff, style {style} ({kind})",
        **_formats(look),
    )
    return _doc(
        case_id,
        "labor",
        built,
        ("labor", kind, f"style:{style}", *(("personal",) if personal else ())),
    )


def _unnamed_labor_doc(case_id: str, hidden: Sequence[str], look_name: str) -> Doc:
    _kind, headers = LABOR_STYLES["snake"]
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = _shifts(rng, rng.randint(24, 48))
    names = dict(headers)
    taken = iter(UNNAMED)
    for field in hidden:
        names[field] = next(taken)
    cols = [
        Col(c.header, c.cell, c.field, ambiguous=c.field in hidden) if c.field in hidden else c
        for c in _labor_cols(names, look)
    ]
    built = flat_document(
        "labor",
        "turni.csv" if look.csv else "turni.xlsx",
        cols,
        items,
        outcome="NOT_AUTOMATIC",
        csv=look.csv,
        sheet_title="Turni",
        note=f"V4 problem corpus - staff, unnamed columns {','.join(hidden)}",
        **_formats(look),
    )
    return _doc(case_id, "labor", built, ("labor", "unnamed", *(f"hidden:{h}" for h in hidden)))


# ==================================================================================================
# purchase invoices
# ==================================================================================================

VENDORS = (
    "Lavanderia Industriale Rossi Srl",
    "Ortofrutta Bianchi Spa",
    "Enel Energia Spa",
    "Pulizie Moderne Snc",
    "Bevande del Garda Srl",
    "Idraulica Verdi di Verdi G.",
)
CATEGORIES = ("Alimentari", "Bevande", "Pulizie", "Utenze", "Manutenzione")
DESCRIPTIONS = (
    "Fornitura mensile",
    "Servizio lavanderia",
    "Consumo energia",
    "Intervento tecnico",
    "Materiale vario",
)


@dataclass(frozen=True, slots=True)
class Bill:
    vendor: str
    number: str
    day: date
    description: str
    net: float
    vat: float
    gross: float
    category: str


def _bills(rng: random.Random, count: int) -> list[Bill]:
    start = date(2026, 9, 1)
    out = []
    for index in range(count):
        net = float(rng.randint(40, 2400))
        vat = round(net * 0.22, 2)
        out.append(
            Bill(
                VENDORS[index % len(VENDORS)],
                f"{2026 - (index % 2)}/{100 + index * 3 + rng.randint(0, 2)}",
                start + timedelta(days=rng.randint(0, 60)),
                rng.choice(DESCRIPTIONS),
                net,
                vat,
                round(net + vat, 2),
                CATEGORIES[index % len(CATEGORIES)],
            )
        )
    return out


COST_FIELDS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "line_description",
    "net_amount",
    "invoice_tax_amount",
    "invoice_gross_amount",
    "cost_category",
)
COST_STYLES: dict[str, tuple[str, dict[str, str]]] = {
    "snake": (
        "plain",
        dict(
            zip(
                COST_FIELDS,
                (
                    "supplier_name",
                    "invoice_number",
                    "invoice_date",
                    "description",
                    "net_amount",
                    "vat_amount",
                    "gross_amount",
                    "expense_category",
                ),
                strict=True,
            )
        ),
    ),
    "italiano": (
        "plain",
        dict(
            zip(
                COST_FIELDS,
                (
                    "Fornitore",
                    "Numero Fattura",
                    "Data Fattura",
                    "Descrizione",
                    "Imponibile",
                    "IVA",
                    "Totale Fattura",
                    "Categoria Spesa",
                ),
                strict=True,
            )
        ),
    ),
    "short": (
        "plain",
        dict(
            zip(
                COST_FIELDS,
                ("Vendor", "Inv No", "Inv Date", "Details", "Net", "VAT", "Gross", "Category"),
                strict=True,
            )
        ),
    ),
    "erp": (
        "plain",
        dict(
            zip(
                COST_FIELDS,
                (
                    "VENDOR_NAME",
                    "DOCUMENT_NO",
                    "DOCUMENT_DATE",
                    "ITEM_DESCRIPTION",
                    "TAXABLE_AMOUNT",
                    "VAT_AMOUNT",
                    "TOTAL_INCL_VAT",
                    "COST_TYPE",
                ),
                strict=True,
            )
        ),
    ),
    "camel": (
        "camel",
        dict(
            zip(
                COST_FIELDS,
                (
                    "SupplierName",
                    "InvoiceNumber",
                    "InvoiceDate",
                    "Description",
                    "NetAmount",
                    "VatAmount",
                    "GrossAmount",
                    "ExpenseCategory",
                ),
                strict=True,
            )
        ),
    ),
    "glued": (
        "glued",
        dict(
            zip(
                COST_FIELDS,
                (
                    "suppliername",
                    "invoicenumber",
                    "invoicedate",
                    "description",
                    "netamount",
                    "vatamount",
                    "grossamount",
                    "expensecategory",
                ),
                strict=True,
            )
        ),
    ),
    "typo": (
        "typo",
        dict(
            zip(
                COST_FIELDS,
                (
                    "Suplier Name",
                    "Invoce Number",
                    "Invoice Dat",
                    "Descripton",
                    "Net Amout",
                    "Vat Amout",
                    "Gross Amout",
                    "Expense Categroy",
                ),
                strict=True,
            )
        ),
    ),
    "qualifier": (
        "qualifier",
        dict(
            zip(
                COST_FIELDS,
                (
                    "Supplier *",
                    "Invoice No. (progressive)",
                    "Invoice Date (dd/mm/yyyy)",
                    "Description",
                    "Net Amount (EUR)",
                    "VAT Amount (EUR)",
                    "Gross Amount (EUR)",
                    "Category",
                ),
                strict=True,
            )
        ),
    ),
}


def _cost_cols(headers: dict[str, str], look: Look) -> list[Col]:
    return [
        Col(headers["supplier_name"], lambda b: b.vendor, "supplier_name"),
        Col(headers["invoice_number"], lambda b: b.number, "invoice_number"),
        Col(headers["invoice_date"], lambda b: date_cell(b.day, look.dates), "invoice_date"),
        Col(headers["line_description"], lambda b: b.description, "line_description"),
        Col(headers["net_amount"], lambda b: money_cell(b.net, look.money), "net_amount"),
        Col(
            headers["invoice_tax_amount"],
            lambda b: money_cell(b.vat, look.money),
            "invoice_tax_amount",
        ),
        Col(
            headers["invoice_gross_amount"],
            lambda b: money_cell(b.gross, look.money),
            "invoice_gross_amount",
        ),
        Col(headers["cost_category"], lambda b: b.category, "cost_category"),
    ]


def _cost_doc(
    case_id: str, style: str, look_name: str, *, override: Mapping[str, str] | None = None
) -> Doc:
    kind, headers = COST_STYLES[style]
    if override:
        kind, headers = "typo_one", {**headers, **override}
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = _bills(rng, rng.randint(14, 30))
    built = flat_document(
        "costs",
        f"{style}.csv" if look.csv else f"{style}.xlsx",
        _cost_cols(headers, look),
        items,
        csv=look.csv,
        tolerated=("COLUMN_MEANING", "CATEGORY_LABELS") if kind == "typo" else ("CATEGORY_LABELS",),
        sheet_title="Fatture",
        note=f"V4 problem corpus - invoices, style {style} ({kind})",
        **_formats(look),
    )
    return _doc(case_id, "costs", built, ("costs", kind, f"style:{style}"))


def _unnamed_cost_doc(case_id: str, hidden: Sequence[str], look_name: str) -> Doc:
    _kind, headers = COST_STYLES["snake"]
    look = LOOKS[look_name]
    rng = _rng(case_id)
    items = _bills(rng, rng.randint(14, 30))
    names = dict(headers)
    taken = iter(UNNAMED)
    for field in hidden:
        names[field] = next(taken)
    cols = [
        Col(c.header, c.cell, c.field, ambiguous=c.field in hidden) if c.field in hidden else c
        for c in _cost_cols(names, look)
    ]
    built = flat_document(
        "costs",
        "acquisti.csv" if look.csv else "acquisti.xlsx",
        cols,
        items,
        outcome="NOT_AUTOMATIC",
        csv=look.csv,
        sheet_title="Fatture",
        note=f"V4 problem corpus - invoices, unnamed columns {','.join(hidden)}",
        **_formats(look),
    )
    return _doc(case_id, "costs", built, ("costs", "unnamed", *(f"hidden:{h}" for h in hidden)))


# ==================================================================================================
# the corpus
# ==================================================================================================


def _doc(case_id: str, card: str, built: Built, tags: Sequence[str]) -> Doc:
    return Doc(
        id=case_id,
        card=built.card or card,
        filename=built.filename,
        content=built.content,
        golden=built.golden,
        tags=(*tags, "csv" if built.filename.endswith(".csv") else "xlsx", "problem-corpus"),
        structure=structure_of(built),
        sheet_count=max(1, len(built.sheets)),
    )


_BOOKING_LOOKS = ("xlsx", "csv_it", "csv_iso")
_OTHER_LOOKS = ("xlsx", "csv_it")

# which columns of a bookings file have no helpful header, one document each
_UNNAMED_BOOKINGS: tuple[tuple[str, ...], ...] = (
    ("status",),
    ("channel",),
    ("source_record_id",),
    ("status", "channel"),
    ("check_in", "check_out"),
    ("booked_at", "check_in", "check_out"),
    ("source_record_id", "channel"),
    ("status", "source_record_id"),
)
_UNNAMED_LABOR: tuple[tuple[str, ...], ...] = (
    ("department",),
    ("work_date",),
    ("department", "work_date"),
)
#
# CORPUS FIX (recorded in the report): the first version also had a document whose ONLY nameless
# column
# was the cost category, an optional field. Its truth said "never automatic", but an import that
# simply leaves an optional column out is safe and a careful person would accept it; V3 read it as
# READY and was scored a false automation by MY truth. That was a bug of the truth, found from the
# V3
# baseline before any V4 result existed, and the document was removed.
_UNNAMED_COSTS: tuple[tuple[str, ...], ...] = (
    ("invoice_date",),
    ("invoice_number",),
    ("cost_category", "invoice_date"),
)


def build_problem_corpus() -> list[Doc]:
    docs: list[Doc] = []
    for style in BOOKING_STYLES:
        for look in _BOOKING_LOOKS:
            docs.append(_booking_doc(f"PB_{style}_{look}", style, look))
    # personal data riding along, in files read by name
    for style in ("snake", "gestionale", "camel", "friendly_en"):
        docs.append(
            _booking_doc(f"PB_{style}_personal", style, "xlsx", extras=("personal", "junk"))
        )
    for number, hidden in enumerate(_UNNAMED_BOOKINGS, start=1):
        docs.append(
            _unnamed_booking_doc(
                f"PB_unnamed{number:02d}", hidden, "xlsx" if number % 2 else "csv_it"
            )
        )
    for style in LABOR_STYLES:
        for look in _OTHER_LOOKS:
            docs.append(_labor_doc(f"PL_{style}_{look}", style, look))
    for style in ("snake", "camel"):
        docs.append(_labor_doc(f"PL_{style}_personal", style, "xlsx", personal=True))
    for number, hidden in enumerate(_UNNAMED_LABOR, start=1):
        docs.append(
            _unnamed_labor_doc(
                f"PL_unnamed{number:02d}", hidden, "xlsx" if number % 2 else "csv_it"
            )
        )
    for style in COST_STYLES:
        for look in _OTHER_LOOKS:
            docs.append(_cost_doc(f"PC_{style}_{look}", style, look))
    for number, hidden in enumerate(_UNNAMED_COSTS, start=1):
        docs.append(
            _unnamed_cost_doc(f"PC_unnamed{number:02d}", hidden, "xlsx" if number % 2 else "csv_it")
        )
    return docs


# ADDED AFTER THE FIRST V4 MEASUREMENT, and labelled so (it is NOT part of the headline numbers):
# the
# `typo` kind above misspells EVERY header of a file, which no person does, and which cannot show
# what
# a reader of spellings is worth (eight unsure columns are more than the product asks one by one, so
# the file goes to the matching screen whatever a reader does). A realistic misspelling is ONE
# header in an otherwise clean file. These documents are one clean file each with exactly one header
# misspelled; written knowing V3's and V4's results on the main corpus, so they test a hypothesis
# the main corpus could not, not the engine's tuning.
SINGLE_TYPOS: dict[str, tuple[str, dict[str, str]]] = {
    "bookings": (
        "friendly_en",
        {
            "source_record_id": "Reservaton Number",
            "booked_at": "Date Bokked",
            "check_in": "Arival Date",
            "check_out": "Departur Date",
            "status": "Reservation Statuss",
            "rooms": "Number of Roms",
            "room_revenue": "Room Totl",
            "channel": "Booking Sorce",
        },
    ),
    "labor": (
        "sched",
        {
            "department": "Departmnt",
            "planned_hours": "Schedulled Hours",
            "actual_hours": "Hours Workd",
        },
    ),
    "costs": (
        "snake",
        {
            "supplier_name": "suplier_name",
            "invoice_number": "invoice_numbr",
            "line_description": "descripton",
            "net_amount": "net_amout",
            "invoice_gross_amount": "gross_amout",
            "cost_category": "expense_categroy",
        },
    ),
}


def build_single_typo_corpus() -> list[Doc]:
    """One clean file per misspelled header (see the note above)."""
    docs: list[Doc] = []
    for field, header in SINGLE_TYPOS["bookings"][1].items():
        for look in ("xlsx", "csv_it"):
            docs.append(
                _booking_doc(
                    f"PT_bookings_{field}_{look}",
                    SINGLE_TYPOS["bookings"][0],
                    look,
                    override={field: header},
                )
            )
    for field, header in SINGLE_TYPOS["labor"][1].items():
        for look in ("xlsx", "csv_it"):
            docs.append(
                _labor_doc(
                    f"PT_labor_{field}_{look}",
                    SINGLE_TYPOS["labor"][0],
                    look,
                    override={field: header},
                )
            )
    for field, header in SINGLE_TYPOS["costs"][1].items():
        for look in ("xlsx", "csv_it"):
            docs.append(
                _cost_doc(
                    f"PT_costs_{field}_{look}",
                    SINGLE_TYPOS["costs"][0],
                    look,
                    override={field: header},
                )
            )
    return docs


# the three headers the brief names, kept as a small focused set for the "why" report
NAMED_HEADERS = ("reservation_code", "booking_status", "room_total")


def named_header_docs(docs: Sequence[Doc]) -> list[Doc]:
    return [d for d in docs if d.id.startswith("PB_snake_")]


Maker = Callable[[random.Random], Built]

__all__ = [
    "NAMED_HEADERS",
    "build_problem_corpus",
    "build_single_typo_corpus",
    "named_header_docs",
]
