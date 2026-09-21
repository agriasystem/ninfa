"""Helpers shared by the Gate 7 (Cost CPOR anomaly) tests. Synthetic data only.

Two families: PURE builders (aggregates, lead-time-0 rows, denominators, metrics, month worlds)
for the detector, the statistics and the selection, and a DB world that stores real snapshots
and real canonical invoices for the service.
"""

import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, event, insert
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.intelligence.costs.aggregation import build_period_metric, index_costs
from app.modules.intelligence.costs.occupancy import build_denominator
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.intelligence.costs.types import (
    CostPeriodMetric,
    MonthlyCostAggregate,
    OccupancyDenominator,
)
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.models import (
    DocumentKind,
    Invoice,
    InvoiceLine,
    ResolutionMethod,
    SourceFormat,
)
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import SnapshotHistoryRow
from app.modules.suppliers.models import Supplier
from tests.expected_support import snapshot_row
from tests.support import BookingFactory, Tenant

D = Decimal
OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
LAUNDRY = CostCategory.LAUNDRY
UTILITIES = CostCategory.UTILITIES
OTHER = CostCategory.OTHER
EUR, USD = "EUR", "USD"
WORKSPACE, PROPERTY, SOURCE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
FINGERPRINT = "f" * 64


def month(year: int, number: int) -> CalendarMonth:
    return CalendarMonth(year, number)


# --- pure builders --------------------------------------------------------------------------------


def aggregate(
    period: CalendarMonth,
    category: CostCategory,
    net: str | Decimal,
    *,
    absolute: str | Decimal | None = None,
    currency: str = EUR,
    confidence: str | Decimal = "80",
    invoices: int = 1,
    lines: int = 1,
    credit_lines: int = 0,
    credit_cost: str | Decimal = "0",
) -> MonthlyCostAggregate:
    """What the database returns for one (month, currency, category)."""
    net_cost = D(net)
    absolute_cost = net_cost.copy_abs() if absolute is None else D(absolute)
    # a classified line carries its confidence, OTHER carries 0 (UNCLASSIFIED)
    line_confidence = D(0) if category == OTHER else D(confidence)
    return MonthlyCostAggregate(
        month=period.start,
        currency=currency,
        cost_category=category,
        net_cost=net_cost,
        absolute_cost=absolute_cost,
        confidence_weighted_cost=absolute_cost * line_confidence,
        invoice_count=invoices,
        line_count=lines,
        credit_note_line_count=credit_lines,
        credit_note_cost=D(credit_cost),
    )


def lead_zero_row(
    day: date,
    rooms: int,
    *,
    origin: SnapshotOrigin = OBSERVED,
    uncertain: int = 0,
) -> SnapshotHistoryRow:
    return SnapshotHistoryRow(
        snapshot_id=uuid.uuid4(),
        snapshot_local_date=day,
        stay_date=day,
        origin=origin,
        rooms_on_books=rooms,
        uncertain_rooms=uncertain,
        adr_on_books=D("100.00") if rooms > 0 else None,
    )


def day_rows(
    period: CalendarMonth,
    rooms: int | Sequence[int] = 10,
    *,
    reconstructed: Iterable[int] = (),
    uncertain: Iterable[int] = (),
    missing: Iterable[int] = (),
) -> dict[date, SnapshotHistoryRow]:
    """Lead-time-0 rows for the days of a month (day numbers 1-based in the option lists)."""
    days = period.day_list()
    per_day = [rooms] * len(days) if isinstance(rooms, int) else list(rooms)
    reconstructed_set, uncertain_set, missing_set = set(reconstructed), set(uncertain), set(missing)
    rows: dict[date, SnapshotHistoryRow] = {}
    for number, day in enumerate(days, start=1):
        if number in missing_set:
            continue
        rows[day] = lead_zero_row(
            day,
            per_day[number - 1],
            origin=RECONSTRUCTED if number in reconstructed_set | uncertain_set else OBSERVED,
            uncertain=1 if number in uncertain_set else 0,
        )
    return rows


def denominator(
    period: CalendarMonth, rooms: int | Sequence[int] = 10, **options: Any
) -> OccupancyDenominator:
    return build_denominator(period, day_rows(period, rooms, **options))


@dataclass
class Ledger:
    """A pure month world: costs and occupancy per month, built by the real metric builder."""

    costs: list[MonthlyCostAggregate] = field(default_factory=list)
    occupancy: dict[CalendarMonth, OccupancyDenominator] = field(default_factory=dict)

    def cost(self, period: CalendarMonth, category: CostCategory, net: str, **options: Any) -> None:
        self.costs.append(aggregate(period, category, net, **options))

    def rooms(self, period: CalendarMonth, rooms: int | Sequence[int] = 10, **options: Any) -> None:
        self.occupancy[period] = denominator(period, rooms, **options)

    def metric(
        self, period: CalendarMonth, category: CostCategory = LAUNDRY, currency: str = EUR
    ) -> CostPeriodMetric:
        empty = build_denominator(period, {})  # nothing stored: every day missing
        return build_period_metric(
            workspace_id=WORKSPACE,
            property_id=PROPERTY,
            booking_data_source_id=SOURCE,
            month=period,
            cost_category=category,
            currency=currency,
            costs=index_costs(self.costs),
            denominator=self.occupancy.get(period, empty),
        )

    def metric_of(
        self, category: CostCategory = LAUNDRY, currency: str = EUR
    ) -> Callable[[CalendarMonth], CostPeriodMetric]:
        return lambda period: self.metric(period, category, currency)


def cpor_history(
    values: Mapping[CalendarMonth, str],
    *,
    rooms: int = 10,
    category: CostCategory = LAUNDRY,
    currency: str = EUR,
    reconstructed_days: int = 0,
    other: str | None = None,
    confidence: str = "80",
) -> Ledger:
    """A ledger where each month has a CPOR of exactly `value` (net = value * rooms * days).

    `other` adds an OTHER cost of that amount to every month (to shape the coverage).
    """
    ledger = Ledger()
    for period, value in values.items():
        ledger.cost(
            period,
            category,
            str(D(value) * rooms * period.days),
            currency=currency,
            confidence=confidence,
        )
        if other is not None:
            ledger.cost(period, OTHER, other, currency=currency)
        ledger.rooms(period, rooms, reconstructed=range(1, reconstructed_days + 1))
    return ledger


# The months a July-August-September target compares with: eight of them, all in the window.
AUGUST = month(2026, 8)
COMPARABLE_MONTHS = [
    month(2026, 7),
    month(2026, 6),
    month(2025, 10),
    month(2025, 9),
    month(2025, 8),
    month(2025, 7),
    month(2025, 6),
    month(2024, 10),
]


# --- database world -------------------------------------------------------------------------------


@contextmanager
def statements_of(session: Session) -> Iterator[list[tuple[str, Any]]]:
    """Every SQL statement (text, parameters) the session's connection executes meanwhile."""
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[tuple[str, Any]] = []

    def record(*args: Any) -> None:
        captured.append((str(args[2]), args[3]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


@dataclass
class CostWorld:
    """One tenant with a BOOKINGS data source (the denominator) and a COSTS data source."""

    session: Session
    tenant: Tenant
    booking_source: DataSource
    cost_source: DataSource
    supplier_id: uuid.UUID
    job_id: uuid.UUID
    file_id: uuid.UUID
    numbers: Iterator[int] = field(default_factory=lambda: iter(range(1, 10**9)))

    @classmethod
    def create(cls, session: Session, factory: BookingFactory) -> "CostWorld":
        tenant = factory.tenant()  # its data source is a BOOKINGS one
        cost_source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
        job = factory.import_job(cost_source)
        file = factory.import_file(job)
        supplier = Supplier(
            workspace_id=tenant.workspace.id, legal_name="Fornitore", normalized_name="fornitore"
        )
        session.add(supplier)
        session.flush()
        return cls(session, tenant, tenant.data_source, cost_source, supplier.id, job.id, file.id)

    @property
    def context(self) -> TenantContext:
        return self.tenant.context

    def service(self) -> CostDecisionService:
        return CostDecisionService(self.session, self.context)

    # --- snapshots ---------------------------------------------------------------------------

    def lead_zero(
        self,
        period: CalendarMonth,
        rooms: int | Sequence[int] = 10,
        *,
        reconstructed: Iterable[int] = (),
        uncertain: Iterable[int] = (),
        missing: Iterable[int] = (),
        data_source_id: uuid.UUID | None = None,
    ) -> None:
        """One lead-time-0 snapshot per day of the month (day numbers are 1-based)."""
        days = period.day_list()
        per_day = [rooms] * len(days) if isinstance(rooms, int) else list(rooms)
        reconstructed_set, uncertain_set, missing_set = (
            set(reconstructed),
            set(uncertain),
            set(missing),
        )
        rows = []
        for number, day in enumerate(days, start=1):
            if number in missing_set:
                continue
            row = snapshot_row(
                self.tenant,
                day,
                day,
                rooms=per_day[number - 1],
                origin=RECONSTRUCTED if number in reconstructed_set | uncertain_set else OBSERVED,
                uncertain_rooms=1 if number in uncertain_set else 0,
                data_source_id=data_source_id,
            )
            row["as_of_at"] = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
                hours=20
            )
            rows.append(row)
        if rows:
            self.session.execute(insert(BookingSnapshot), rows)

    def snapshot(
        self,
        snapshot_day: date,
        stay_day: date,
        rooms: int,
        *,
        origin: SnapshotOrigin = OBSERVED,
        data_source_id: uuid.UUID | None = None,
    ) -> None:
        """A single arbitrary snapshot (to prove that lead time > 0 is never used)."""
        row = snapshot_row(
            self.tenant,
            snapshot_day,
            stay_day,
            rooms=rooms,
            origin=origin,
            data_source_id=data_source_id,
        )
        row["as_of_at"] = datetime.combine(snapshot_day, datetime.min.time(), tzinfo=UTC)
        self.session.execute(insert(BookingSnapshot), [row])

    # --- invoices ----------------------------------------------------------------------------

    def invoice(
        self,
        day: date,
        lines: Sequence[tuple[CostCategory, str] | tuple[CostCategory, str, str]],
        *,
        currency: str = EUR,
        kind: DocumentKind = DocumentKind.INVOICE,
        number: str | None = None,
    ) -> uuid.UUID:
        """A canonical invoice with lines `(category, signed line_total[, confidence])`.

        The amounts are stored AS GIVEN: Gate 6 already made a credit note negative, so pass
        negative totals for a credit note. OTHER lines are UNCLASSIFIED (confidence 0).
        """
        invoice_id = uuid.uuid4()
        number = number or f"N-{next(self.numbers)}"
        source, job_id, file_id = self.cost_source, self.job_id, self.file_id
        self.session.execute(
            insert(Invoice),
            [
                {
                    "id": invoice_id,
                    "workspace_id": self.tenant.workspace.id,
                    "property_id": self.tenant.property.id,
                    "data_source_id": source.id,
                    "supplier_id": self.supplier_id,
                    "invoice_number": number,
                    "normalized_invoice_number": number.upper(),
                    "invoice_date": day,
                    "document_type_code": None,
                    "document_kind": kind,
                    "currency": currency,
                    "net_amount": None,
                    "tax_amount": None,
                    "gross_amount": None,
                    "source_format": SourceFormat.CSV,
                    "source_import_job_id": job_id,
                    "source_import_file_id": file_id,
                    "source_fingerprint": FINGERPRINT,
                    "supplier_resolution_method": ResolutionMethod.CREATED_NEW,
                }
            ],
        )
        rows = []
        for position, line in enumerate(lines, start=1):
            category, total = line[0], line[1]
            classified = category != OTHER
            confidence = D(line[2]) if len(line) == 3 else D("80")
            rows.append(
                {
                    "workspace_id": self.tenant.workspace.id,
                    "invoice_id": invoice_id,
                    "source_line_number": position,
                    "description_raw": f"riga {position}",
                    "description_normalized": f"riga {position}",
                    "quantity": None,
                    "unit": None,
                    "unit_price": None,
                    "line_total": D(total),
                    "vat_rate": None,
                    "cost_category": category,
                    "classification_confidence": confidence if classified else D("0"),
                    "classification_method": (
                        ClassificationMethod.DETERMINISTIC_RULE
                        if classified
                        else ClassificationMethod.UNCLASSIFIED
                    ),
                }
            )
        self.session.execute(insert(InvoiceLine), rows)
        return invoice_id

    def other_cost_source(self, factory: BookingFactory) -> DataSource:
        """A second COSTS data source of the property (for the cross-source tests)."""
        return factory.data_source(self.tenant.property, DataSourceDomain.COSTS)

    def invoice_from(
        self,
        factory: BookingFactory,
        source: DataSource,
        day: date,
        lines: Sequence[tuple[CostCategory, str]],
        *,
        number: str,
        currency: str = EUR,
    ) -> uuid.UUID:
        """An invoice whose recorded source (job/file/data source) is another COSTS source."""
        job = factory.import_job(source)
        file = factory.import_file(job)
        previous = (self.cost_source, self.job_id, self.file_id)
        self.cost_source, self.job_id, self.file_id = source, job.id, file.id
        try:
            return self.invoice(day, lines, number=number, currency=currency)
        finally:
            self.cost_source, self.job_id, self.file_id = previous

    def history(
        self,
        values: Mapping[CalendarMonth, str],
        *,
        rooms: int = 10,
        category: CostCategory = LAUNDRY,
        currency: str = EUR,
        reconstructed_days: int = 0,
        other: str | None = None,
        snapshots: bool = True,
    ) -> None:
        """For each month: lead-0 snapshots with `rooms` per day and ONE invoice whose category
        line makes the month's CPOR exactly `value` (net = value * rooms * days).

        `snapshots=False` adds the invoices only (the months already have their snapshots).
        """
        for period, value in values.items():
            if snapshots:
                self.lead_zero(period, rooms, reconstructed=range(1, reconstructed_days + 1))
            lines: list[tuple[CostCategory, str]] = [
                (category, str(D(value) * rooms * period.days))
            ]
            if other is not None:
                lines.append((OTHER, other))
            self.invoice(period.start + timedelta(days=9), lines, currency=currency)


def counts(session: Session) -> dict[str, int]:
    """Row counts of every table Gate 7 reads (to prove that nothing is written)."""
    from sqlalchemy import func, select

    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (BookingSnapshot, Invoice, InvoiceLine, Supplier)
    }
