"""The sources of the Source Learning benchmark: 12 families, 8 versions each = 96 documents.

A family is a source as a hotel keeps it: a staff export, a bookings export, a cost register, with
the hotel's OWN words for its columns. Ten of them are written in words the engine cannot read on
its own, so the first time somebody has to decide (answer a question, or match the columns by
hand); two are written in plain words and are READ BY THE ENGINE ALONE (controls: nothing should be
learned from them, and nothing should be harmed).

Versions, in the order a source lives:

    V1  the first file          the person decides; the import remembers it
    V2  next month              same structure, other data
    V3  columns moved           the last column is now the first
    V4  a junk column           a column nobody asked for appears
    V5  cosmetic headers        case, spacing, punctuation - and a synonym the engine reads the same
    V6  a new column            something new in the middle
    V7  a known column gone     a column the person decided is no longer there
    V8  a semantic conflict     a column the person decided now holds something else

The truth of every version is written here, next to the document: which header means which field.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.ingestion.models import DataSourceDomain

JUNK = "Colonna extra"
NEW = "Annotazioni"


class Expect(StrEnum):
    FIRST = "FIRST"  # V1: the person decides
    EXACT = "EXACT"  # the same source: nothing asked again
    COMPATIBLE = "COMPATIBLE"  # the same source with something added: nothing asked again
    MISSING = "MISSING"  # a known column is gone: it is NOT reused, the rest is
    CONFLICT = "CONFLICT"  # the file contradicts the memory: not reused, never automatic


@dataclass(frozen=True, slots=True)
class Family:
    id: str
    domain: DataSourceDomain
    card: str  # the card the person chose: labor | bookings | costs
    columns: Mapping[str, str]  # header -> kind of its values (see source_learning_support)
    truth: Mapping[str, str]  # header -> the field it means
    # how the person confirms at V1: answers to the questions, or a matching built by hand
    answers: Mapping[str, Any] = field(default_factory=dict)
    manual: bool = False
    # the headers the person decides (the engine could not): what is learned
    decided: tuple[str, ...] = ()
    # a rename the ENGINE reads the same (a synonym), for the cosmetic version
    synonym: tuple[str, str] | None = None
    # the column that disappears in V7 and the one that changes meaning in V8
    drop: str = ""
    conflict: str = ""
    # a control family is read by the engine alone: nothing to learn
    control: bool = False

    @property
    def labor(self) -> bool:
        return self.domain == DataSourceDomain.LABOR


@dataclass(frozen=True, slots=True)
class Version:
    key: str
    title: str
    expect: Expect
    columns: Mapping[str, str]
    truth: Mapping[str, str]
    month: int
    rows: int
    changed: tuple[str, ...] = ()  # headers that are new or different in THIS version
    gone: tuple[str, ...] = ()  # fields whose column is no longer there
    conflicted: tuple[str, ...] = ()  # headers whose values changed meaning


def _cosmetic(header: str) -> str:
    return header.upper().replace(" ", "  ") + ":"


def versions(family: Family) -> list[Version]:
    base, truth = dict(family.columns), dict(family.truth)
    last = list(base)[-1]
    moved = {last: base[last], **{h: k for h, k in base.items() if h != last}}

    cosmetic_columns: dict[str, str] = {}
    cosmetic_truth: dict[str, str] = {}
    renamed: list[str] = []
    for header, kind in base.items():
        new = _cosmetic(header)
        if family.synonym and header == family.synonym[0]:
            new = family.synonym[1]
        cosmetic_columns[new] = kind
        if header in truth:
            cosmetic_truth[new] = truth[header]
        renamed.append(new)

    with_new = dict(base)
    items = list(with_new.items())
    items.insert(1, (NEW, "note"))
    dropped_field = truth[family.drop] if family.drop else ""
    retyped = {h: ("note" if h == family.conflict else k) for h, k in base.items()}
    return [
        Version("V1", "the first file", Expect.FIRST, base, truth, 10, 12),
        Version("V2", "next month, other data", Expect.EXACT, base, truth, 11, 20),
        Version("V3", "columns moved", Expect.EXACT, moved, truth, 11, 14, changed=(last,)),
        Version(
            "V4",
            "a junk column",
            Expect.COMPATIBLE,
            {**base, JUNK: "junk"},
            truth,
            11,
            16,
            changed=(JUNK,),
        ),
        Version(
            "V5",
            "cosmetic headers",
            Expect.EXACT,
            cosmetic_columns,
            cosmetic_truth,
            11,
            18,
            changed=tuple(renamed),
        ),
        Version("V6", "a new column", Expect.COMPATIBLE, dict(items), truth, 11, 12, (NEW,)),
        Version(
            "V7",
            "a known column gone",
            Expect.MISSING,
            {h: k for h, k in base.items() if h != family.drop},
            {h: f for h, f in truth.items() if h != family.drop},
            11,
            15,
            gone=(dropped_field,),
        ),
        Version(
            "V8",
            "a column changed meaning",
            Expect.CONFLICT,
            retyped,
            {h: f for h, f in truth.items() if h != family.conflict},
            11,
            13,
            changed=(family.conflict,),
            conflicted=(family.conflict,),
        ),
    ]


L = DataSourceDomain.LABOR
B = DataSourceDomain.BOOKINGS
C = DataSourceDomain.COSTS

FAMILIES: tuple[Family, ...] = (
    # --- staff ---
    Family(
        "L1-ore-a-b",
        L,
        "labor",
        {"Giorno": "day", "Ore A": "planned", "Ore B": "actual", "Settore": "dept"},
        {
            "Giorno": "work_date",
            "Ore A": "planned_hours",
            "Ore B": "actual_hours",
            "Settore": "role",
        },
        answers={"column_fields": {"Ore A": "planned_hours", "Ore B": "actual_hours"}},
        decided=("Ore A", "Ore B"),
        synonym=("Settore", "Reparto"),
        drop="Ore B",
        conflict="Ore A",
    ),
    Family(
        "L2-ore-1-2",
        L,
        "labor",
        {"Data": "day", "Ore 1": "planned", "Ore 2": "actual", "Area": "dept"},
        {"Data": "work_date", "Ore 1": "planned_hours", "Ore 2": "actual_hours", "Area": "role"},
        answers={"column_fields": {"Ore 1": "planned_hours", "Ore 2": "actual_hours"}},
        decided=("Ore 1", "Ore 2"),
        synonym=("Area", "Reparto"),
        drop="Ore 2",
        conflict="Ore 1",
    ),
    Family(
        "L3-ore-base",
        L,
        "labor",
        {"Giorno": "day", "Ore base": "planned", "Ore extra": "actual", "Squadra": "dept"},
        {
            "Giorno": "work_date",
            "Ore base": "planned_hours",
            "Ore extra": "actual_hours",
            "Squadra": "role",
        },
        answers={"column_fields": {"Ore base": "planned_hours", "Ore extra": "actual_hours"}},
        decided=("Ore base", "Ore extra"),
        synonym=("Squadra", "Reparto"),
        drop="Ore extra",
        conflict="Ore base",
    ),
    Family(
        "L4-h1-h2",
        L,
        "labor",
        {"Dt": "day", "H1": "planned", "H2": "actual", "Rep": "dept"},
        {"Dt": "work_date", "H1": "planned_hours", "H2": "actual_hours", "Rep": "role"},
        manual=True,
        decided=("Dt", "H1", "H2", "Rep"),
        synonym=("Rep", "Reparto"),
        drop="H2",
        conflict="H1",
    ),
    Family(
        "L5-gruppo",
        L,
        "labor",
        {"Giorno": "day", "Gruppo di lavoro": "dept", "Ore previste": "planned"},
        {"Giorno": "work_date", "Ore previste": "planned_hours"},
        # no column says the department: the person says it ONCE, for all the rows
        answers={"department_value": "FRONT_OFFICE"},
        decided=(),
        drop="Ore previste",
        conflict="Ore previste",
    ),
    # --- bookings ---
    Family(
        "B1-pratica",
        B,
        "bookings",
        {
            "Pratica": "ref",
            "Creata": "booked",
            "Dal": "checkin",
            "Al": "checkout",
            "Esito": "status",
            "Unita": "rooms",
            "Valore": "revenue",
            "Fonte": "channel",
        },
        {
            "Pratica": "source_record_id",
            "Creata": "booked_at",
            "Dal": "check_in",
            "Al": "check_out",
            "Esito": "status",
            "Unita": "rooms",
            "Valore": "room_revenue",
            "Fonte": "channel",
        },
        manual=True,
        decided=("Pratica", "Esito", "Unita", "Valore"),
        drop="Valore",
        conflict="Valore",
    ),
    Family(
        "B2-cod",
        B,
        "bookings",
        {
            "Cod": "ref",
            "Emissione": "booked",
            "Arrivo": "checkin",
            "Partenza": "checkout",
            "Stato": "status",
            "Cam": "rooms",
            "Importo": "revenue",
            "Origine": "channel",
        },
        {
            "Cod": "source_record_id",
            "Emissione": "booked_at",
            "Arrivo": "check_in",
            "Partenza": "check_out",
            "Stato": "status",
            "Cam": "rooms",
            "Importo": "room_revenue",
            "Origine": "channel",
        },
        manual=True,
        decided=("Cod", "Emissione", "Cam", "Importo"),
        drop="Importo",
        conflict="Importo",
    ),
    Family(
        "B3-id",
        B,
        "bookings",
        {
            "ID": "ref",
            "Inserita": "booked",
            "Entrata": "checkin",
            "Uscita": "checkout",
            "Situazione": "status",
            "Stanze": "rooms",
            "Prezzo": "revenue",
            "Sorgente": "channel",
        },
        {
            "ID": "source_record_id",
            "Inserita": "booked_at",
            "Entrata": "check_in",
            "Uscita": "check_out",
            "Situazione": "status",
            "Stanze": "rooms",
            "Prezzo": "room_revenue",
            "Sorgente": "channel",
        },
        manual=True,
        decided=("Entrata", "Uscita", "Situazione", "Stanze", "Prezzo", "Sorgente"),
        drop="Prezzo",
        conflict="Prezzo",
    ),
    # --- costs ---
    Family(
        "C1-forn",
        C,
        "costs",
        {"Forn.": "supplier", "Doc": "invno", "Del": "invdate", "Voce": "desc", "Tot": "net"},
        {
            "Forn.": "supplier_name",
            "Doc": "invoice_number",
            "Del": "invoice_date",
            "Voce": "line_description",
            "Tot": "line_total",
        },
        manual=True,
        decided=("Forn.", "Del", "Tot"),
        drop="Tot",
        conflict="Tot",
    ),
    Family(
        "C2-ragione",
        C,
        "costs",
        {
            "Ragione": "supplier",
            "Rif": "invno",
            "Emesso": "invdate",
            "Dettaglio": "desc",
            "Valore": "net",
        },
        {
            "Ragione": "supplier_name",
            "Rif": "invoice_number",
            "Emesso": "invoice_date",
            "Dettaglio": "line_description",
            "Valore": "line_total",
        },
        manual=True,
        decided=("Ragione", "Rif", "Valore"),
        drop="Valore",
        conflict="Valore",
    ),
    Family(
        "C3-chi",
        C,
        "costs",
        {
            "Chi": "supplier",
            "Numero": "invno",
            "Quando": "invdate",
            "Cosa": "desc",
            "Quanto": "net",
        },
        {
            "Chi": "supplier_name",
            "Numero": "invoice_number",
            "Quando": "invoice_date",
            "Cosa": "line_description",
            "Quanto": "line_total",
        },
        manual=True,
        decided=("Chi", "Quando", "Cosa", "Quanto"),
        drop="Quanto",
        conflict="Quanto",
    ),
    # --- controls: the engine reads them alone, nothing is learned from them ---
    Family(
        "X1-staff-clear",
        L,
        "labor",
        {"Giorno": "day", "Ore previste": "planned", "Ore effettive": "actual", "Reparto": "dept"},
        {
            "Giorno": "work_date",
            "Ore previste": "planned_hours",
            "Ore effettive": "actual_hours",
            "Reparto": "role",
        },
        decided=(),
        drop="Ore effettive",
        conflict="Ore previste",
        control=True,
    ),
    Family(
        "X2-costs-clear",
        C,
        "costs",
        {
            "Fornitore": "supplier",
            "N. fattura": "invno",
            "Data fattura": "invdate",
            "Descrizione": "desc",
            "Importo netto": "net",
        },
        {
            "Fornitore": "supplier_name",
            "N. fattura": "invoice_number",
            "Data fattura": "invoice_date",
            "Descrizione": "line_description",
            "Importo netto": "line_total",
        },
        decided=(),
        drop="Importo netto",
        conflict="Importo netto",
        control=True,
    ),
)
