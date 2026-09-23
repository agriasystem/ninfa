"""MASSERIA NINFA DEMO — PRIORITY V1: builds one shared workspace/property and, on it, drives
each of the five real detector services (Gate 5/7/8/9's own, unmodified) to produce real TRIGGERED
evaluations, plus a real CLEAR, a real INSUFFICIENT_DATA and a real SUPPRESSED_LOW_CONFIDENCE
one, for `test_priority_golden.py`. Every evaluation below - triggered or not - comes from a real
detector service reading real canonical rows; none is ever built by hand as a `PriorityCandidate`
or a source-evaluation substitute.

Every detector gets its OWN dedicated data source(s) on the SAME property (a property may
legitimately have more than one BOOKINGS data source; nothing here reuses one detector's calendar
range for another, so there is zero risk of an unrelated snapshot collision between detectors).
Each scenario below is a direct, minimal adaptation of an already-proven pattern from that gate's
own test suite (`test_revenue_service.py`, `test_distribution_smoke.py`, `test_cost_service.py`,
`test_labor_overstaffing_smoke.py`): nothing here invents new detector behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import ChannelGroup, OtaDependencyEvaluation
from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.suppliers.models import Supplier
from tests.cost_support import EUR, LAUNDRY, CostWorld, month
from tests.distribution_support import ChannelType, DistributionWorld
from tests.expected_support import ELIGIBLE, TARGET_SNAPSHOT_DAY, snapshot_row
from tests.labor_support import LaborTenant, LaborWorld, labor_data_source
from tests.revenue_support import RevenueWorld
from tests.support import BookingFactory, Tenant

_TZ = ZoneInfo("Europe/Rome")  # the property's own default timezone (test_distribution_golden.py)

# The one shared as-of date every forward-dated / as-of-bearing TRIGGERED signal is coherent
# with: REV_PICKUP_LOW/REV_OCCUPANCY_RISK's snapshot_local_date IS `TARGET_SNAPSHOT_DAY`
# (2026-08-01, a fixed constant of the Gate 4/5 fixtures reused here unmodified), so this is the
# one PriorityContext.as_of_local_date the whole golden run uses.
GOLDEN_AS_OF = TARGET_SNAPSHOT_DAY  # 2026-08-01, a Saturday

# The same 12 clean, same-weekday, in-season historical stay dates test_revenue_service.py's own
# `world` fixture uses (`ELIGIBLE`, the 24 Gate 4-eligible comparables, newest first).
CLEAN_STAYS = ELIGIBLE[2:14]

# OTA and Labor's own as-of/target-date are set to the SAME date for as-of coherence.
OTA_TARGET_AS_OF = GOLDEN_AS_OF
LABOR_TARGET = GOLDEN_AS_OF

# Cost is retrospective: its target month must have CONCLUDED before GOLDEN_AS_OF.
COST_TARGET_MONTH = month(2026, 7)  # ends 2026-07-31, one day before GOLDEN_AS_OF
COST_INVOICE_DAY = date(2026, 7, 14)
COST_COMPARABLE_MONTHS = [
    month(2026, 6),
    month(2025, 9),
    month(2025, 8),
    month(2025, 7),
    month(2025, 6),
    month(2025, 5),
    month(2024, 9),
    month(2024, 8),
]


def _historical_weeks_back(anchor: date, count: int) -> list[date]:
    return [anchor - timedelta(weeks=k) for k in range(1, count + 1)]


@dataclass
class PriorityGoldenWorld:
    session: Session
    tenant: Tenant  # the one shared workspace/property every scenario below is built on

    revenue_source: DataSource
    ota_source: DataSource
    ota_clear_source: DataSource
    ota_suppressed_source: DataSource
    cost_booking_source: DataSource
    cost_source: DataSource
    labor_tenant: LaborTenant

    revenue_target_id: UUID
    orphan_target_id: UUID  # a lone OBSERVED snapshot with no Gate 4 baseline: INSUFFICIENT_DATA
    labor_target_booking_snapshot_id: UUID

    def revenue_signals(self) -> tuple[RevenueDecisionEvaluation, RevenueDecisionEvaluation]:
        """REV_PICKUP_LOW and REV_OCCUPANCY_RISK, both TRIGGERED, on the same real target."""
        signals = RevenueDecisionService(
            self.session, self.tenant.context
        ).evaluate_revenue_signals(self.revenue_target_id)
        return signals.pickup_low, signals.occupancy_risk

    def orphan_pickup(self) -> RevenueDecisionEvaluation:
        """A pickup evaluation of a target with no Gate 4 baseline: INSUFFICIENT_DATA."""
        return RevenueDecisionService(self.session, self.tenant.context).evaluate_pickup_low(
            self.orphan_target_id
        )

    def ota_structural(self) -> OtaDependencyEvaluation:
        return OtaDependencyService(self.session, self.tenant.context).evaluate(
            property_id=self.tenant.property.id,
            booking_data_source_id=self.ota_source.id,
            as_of_local_date=OTA_TARGET_AS_OF,
        )

    def ota_clear(self, as_of_local_date: date) -> OtaDependencyEvaluation:
        return OtaDependencyService(self.session, self.tenant.context).evaluate(
            property_id=self.tenant.property.id,
            booking_data_source_id=self.ota_clear_source.id,
            as_of_local_date=as_of_local_date,
        )

    def ota_suppressed(self) -> OtaDependencyEvaluation:
        """A real numeric structural candidate whose historical spread alone drives the
        baseline confidence under 55 (`test_distribution_golden.py`'s own case F, adapted)."""
        return OtaDependencyService(self.session, self.tenant.context).evaluate(
            property_id=self.tenant.property.id,
            booking_data_source_id=self.ota_suppressed_source.id,
            as_of_local_date=OTA_TARGET_AS_OF,
        )

    def cost_anomaly(self) -> CostDecisionEvaluation:
        context = TenantContext(self.tenant.workspace.id)
        return CostDecisionService(self.session, context).evaluate_cpor_anomaly(
            property_id=self.tenant.property.id,
            booking_data_source_id=self.cost_booking_source.id,
            year=COST_TARGET_MONTH.year,
            month=COST_TARGET_MONTH.month,
            cost_category=LAUNDRY,
            currency=EUR,
        )

    def labor_overstaffing(self) -> LaborDecisionEvaluation:
        return LaborDecisionService(self.session, self.labor_tenant.context).evaluate_overstaffing(
            target_booking_snapshot_id=self.labor_target_booking_snapshot_id,
            labor_data_source_id=self.labor_tenant.labor_data_source.id,
            labor_category=LaborCategory.HOUSEKEEPING,
        )


def build_priority_golden_world(session: Session, factory: BookingFactory) -> PriorityGoldenWorld:
    tenant = factory.tenant()  # the shared workspace + property (+ a BOOKINGS source: Revenue's)

    # --- REV_PICKUP_LOW / REV_OCCUPANCY_RISK: both TRIGGERED (test_revenue_service.py's `world`)
    revenue_world = RevenueWorld.create(
        session, factory, tenant=tenant, target_rooms=20, available=40
    )
    revenue_world.own_prior(12)
    revenue_world.curves(CLEAN_STAYS, prior=16, anchor=26, final=34)
    revenue_world.calculate()

    # A second, unrelated OBSERVED target on the SAME data source, far outside the 2026 season,
    # with NO Gate 4 baseline ever computed for it: INSUFFICIENT_DATA / EXPECTED_BASELINE_MISSING.
    orphan_row = snapshot_row(tenant, date(2027, 1, 1), date(2027, 1, 10), rooms=5)
    revenue_world.add(orphan_row)
    orphan_id: UUID = orphan_row["id"]

    # --- REV_OTA_DEPENDENCY: STRUCTURAL TRIGGERED (test_distribution_smoke.py's own scenario)
    ota_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    ota_tenant = Tenant(
        tenant.workspace, tenant.property, ota_source, factory.import_job(ota_source)
    )
    ota_world = DistributionWorld(session, ota_tenant, factory)
    ota_channel = ota_world.channel("Booking.com", channel_type=ChannelType.OTA, is_verified=True)
    direct_channel = ota_world.channel("Direct", channel_type=ChannelType.DIRECT, is_verified=True)
    window_end = OTA_TARGET_AS_OF + timedelta(days=29)
    historical = _historical_weeks_back(OTA_TARGET_AS_OF, 6)
    first_night = min(historical)
    ota_world.uniform_bookings(first_night, window_end, [(ota_channel, 16), (direct_channel, 10)])
    ota_world.booking(
        ota_channel,
        OTA_TARGET_AS_OF,
        window_end + timedelta(days=1),
        rooms=8,
        booked_at=datetime.combine(OTA_TARGET_AS_OF, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=10),
    )
    for as_of in historical:
        ota_world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 26)
    ota_world.snapshot_window(OTA_TARGET_AS_OF, OTA_TARGET_AS_OF, window_end, 34)

    # --- REV_OTA_DEPENDENCY: a separate, CLEAR period (own dedicated source, no interaction)
    ota_clear_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    ota_clear_tenant = Tenant(
        tenant.workspace, tenant.property, ota_clear_source, factory.import_job(ota_clear_source)
    )
    ota_clear_world = DistributionWorld(session, ota_clear_tenant, factory)
    # `booking_channels` is unique per (workspace, property, normalized_name), not per data
    # source: the SAME two channels (already created above, on this same property) are reused.
    clear_ota_channel, clear_direct_channel = ota_channel, direct_channel
    clear_as_of = OTA_TARGET_AS_OF - timedelta(weeks=30)
    clear_window_end = clear_as_of + timedelta(days=29)
    clear_historical = _historical_weeks_back(clear_as_of, 6)
    clear_first_night = min(clear_historical)
    ota_clear_world.uniform_bookings(
        clear_first_night, clear_window_end, [(clear_ota_channel, 20), (clear_direct_channel, 10)]
    )
    for as_of in [clear_as_of, *clear_historical]:
        ota_clear_world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), 30)

    # --- REV_OTA_DEPENDENCY: a real SUPPRESSED_LOW_CONFIDENCE period (own dedicated source),
    # adapted from test_distribution_golden.py's own case F: 5 RECONSTRUCTED_APPROXIMATE
    # historical weeks (never fully observed: caps the baseline at 65), 3 of which stay at a
    # base 5% share and 2 of which jump to 90% via a real, second, later-booked addition (never
    # by editing the first booking) - the resulting historical spread alone already drives the
    # baseline confidence under 55, so a genuine structural candidate (target also at 90%) is
    # suppressed, not triggered.
    ota_suppressed_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    ota_suppressed_tenant = Tenant(
        tenant.workspace,
        tenant.property,
        ota_suppressed_source,
        factory.import_job(ota_suppressed_source),
    )
    ota_suppressed_world = DistributionWorld(session, ota_suppressed_tenant, factory)
    # `booking_channels` is unique per (workspace, property, normalized_name), not per data
    # source: the SAME two channels (already created above, on this same property) are reused.
    suppressed_ota_channel, suppressed_direct_channel = ota_channel, direct_channel
    suppressed_window_end = OTA_TARGET_AS_OF + timedelta(days=29)
    suppressed_weeks = _historical_weeks_back(OTA_TARGET_AS_OF, 5)  # weeks 1-5 back
    suppressed_week3 = suppressed_weeks[2]
    suppressed_first_night = min(suppressed_weeks)
    # Base: 1 OTA / 19 DIRECT (5% share), certain everywhere (weeks 1-5 AND the target).
    ota_suppressed_world.uniform_bookings(
        suppressed_first_night,
        suppressed_window_end,
        [(suppressed_ota_channel, 1), (suppressed_direct_channel, 19)],
    )
    # The jump: 170 more OTA rooms, booked only after week 3's own cutoff - invisible to weeks
    # 3, 4, 5 (older), certain for weeks 1, 2 and the target (newer): (1+170)/(20+170) = 90%.
    suppressed_jump_booked_at = end_of_local_day(suppressed_week3, _TZ) + timedelta(hours=1)
    ota_suppressed_world.booking(
        suppressed_ota_channel,
        suppressed_first_night,
        suppressed_window_end + timedelta(days=1),
        rooms=170,
        booked_at=suppressed_jump_booked_at,
    )
    for as_of in suppressed_weeks[:2]:  # base + jump, 190/night
        ota_suppressed_world.snapshot_window(
            as_of,
            as_of,
            as_of + timedelta(days=29),
            190,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    for as_of in suppressed_weeks[2:]:  # base only, 20/night
        ota_suppressed_world.snapshot_window(
            as_of,
            as_of,
            as_of + timedelta(days=29),
            20,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    ota_suppressed_world.snapshot_window(
        OTA_TARGET_AS_OF, OTA_TARGET_AS_OF, suppressed_window_end, 190
    )  # base + jump too

    # --- COST_CPOR_ANOMALY: TRIGGERED (test_cost_service.py's `triggered_world`, shifted to July
    # so the target month concludes strictly before GOLDEN_AS_OF)
    cost_booking_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    cost_booking_job = factory.import_job(cost_booking_source)
    cost_tenant = Tenant(tenant.workspace, tenant.property, cost_booking_source, cost_booking_job)
    cost_source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    cost_job = factory.import_job(cost_source)
    cost_file = factory.import_file(cost_job)
    supplier = Supplier(
        workspace_id=tenant.workspace.id,
        legal_name="Fornitore Priority Golden",
        normalized_name="fornitore priority golden",
    )
    session.add(supplier)
    session.flush()
    cost_world = CostWorld(
        session,
        cost_tenant,
        cost_booking_source,
        cost_source,
        supplier.id,
        cost_job.id,
        cost_file.id,
    )
    cost_world.history({m: "10" for m in COST_COMPARABLE_MONTHS})
    cost_world.lead_zero(COST_TARGET_MONTH, 10)
    cost_world.invoice(COST_INVOICE_DAY, [(LAUNDRY, "4000.00")])

    # --- LABOR_OVERSTAFFING: TRIGGERED (test_labor_overstaffing_smoke.py's own scenario)
    labor_booking_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    labor_data_src = labor_data_source(factory, tenant.property)
    labor_tenant_obj = LaborTenant(
        workspace=tenant.workspace,
        property=tenant.property,
        booking_data_source=labor_booking_source,
        labor_data_source=labor_data_src,
        booking_import_job=factory.import_job(labor_booking_source),
        labor_import_job=factory.import_job(labor_data_src),
    )
    labor_world = LaborWorld(session, labor_tenant_obj)
    for day in _historical_weeks_back(LABOR_TARGET, 6):
        labor_world.booking_day(day, rooms_on_books=30)
        labor_world.labor_day(LABOR_TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="24")
    labor_target_snapshot = labor_world.booking_day(LABOR_TARGET, rooms_on_books=30)
    labor_world.labor_day(
        LABOR_TARGET, LABOR_TARGET, LaborCategory.HOUSEKEEPING, planned_hours="32"
    )

    session.commit()

    return PriorityGoldenWorld(
        session=session,
        tenant=tenant,
        revenue_source=tenant.data_source,
        ota_source=ota_source,
        ota_clear_source=ota_clear_source,
        ota_suppressed_source=ota_suppressed_source,
        cost_booking_source=cost_booking_source,
        cost_source=cost_source,
        labor_tenant=labor_tenant_obj,
        revenue_target_id=revenue_world.target_id,
        orphan_target_id=orphan_id,
        labor_target_booking_snapshot_id=labor_target_snapshot.id,
    )


__all__ = [
    "COST_INVOICE_DAY",
    "COST_TARGET_MONTH",
    "GOLDEN_AS_OF",
    "LABOR_TARGET",
    "OTA_TARGET_AS_OF",
    "ChannelGroup",
    "PriorityGoldenWorld",
    "build_priority_golden_world",
]
