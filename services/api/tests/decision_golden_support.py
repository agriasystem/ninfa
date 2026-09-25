"""MASSERIA NINFA DEMO — DECISION MEMORY V1: the real pipeline, end to end.

    canonical data -> REAL detector services (Gate 5/7/8/9) -> PriorityService.rank()
    -> DecisionService.sync() -> PostgreSQL Decision Memory

Reuses `tests.priority_golden_support.build_priority_golden_world` UNMODIFIED for the five
canonical Day 1 TRIGGERED evaluations (one per MVP decision type) - it is Gate 10's own, already
proven fixture, and this gate never touches it. On top of the SAME shared workspace/property, this
module adds ONE more real, dedicated `REV_OTA_DEPENDENCY` data source ("the lifecycle OTA source")
built specifically to walk through OPENED -> RESOLVED -> REOPENED across three widely-spaced,
non-overlapping calendar windows, on the SAME booking data source (so its `identity_key` stays
identical across all three) - this is what demonstrates cross-day identity, explicit CLEAR
resolution and reopening, all through the real `OtaDependencyService`, never a hand-built
evaluation.

No `PriorityCandidate`, `Decision` or `DecisionObservation` is ever built by hand as a substitute
for the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.distribution.service import OtaDependencyService
from app.modules.intelligence.distribution.types import OtaDependencyEvaluation
from tests.distribution_support import ChannelType, DistributionWorld
from tests.priority_golden_support import (
    GOLDEN_AS_OF,
    PriorityGoldenWorld,
    build_priority_golden_world,
)
from tests.support import BookingFactory, Tenant

# --- the three widely-spaced, non-overlapping calendar windows -----------------------------------
#
# DAY_1/DAY_2/DAY_3 are all exactly a multiple of 7 days apart (same weekday: Gate 9's own
# comparable-period rule only ever looks at whole weeks back from a target's own as-of, so this is
# what makes each day's 6 weekly historical comparables land where this fixture puts them - no
# other spacing was tried or needed).
DAY_1 = GOLDEN_AS_OF  # 2026-08-01 (a Saturday): the shared golden world's own as-of
DAY_2 = DAY_1 + timedelta(days=35)  # 2026-09-05
DAY_3 = DAY_1 + timedelta(days=70)  # 2026-10-10

# Three contiguous, non-overlapping zones of real, canonical bookings on the lifecycle OTA source,
# EVERY night summing to the SAME total (100 room nights: 90+10 or 20+80) so a `snapshot_window`
# total of 100 is valid everywhere - only the OTA/DIRECT split changes between zones.
_HIGH_ZONE_A_START = date(2026, 6, 1)  # comfortably before Day 1's own 6 historical weeks
_HIGH_ZONE_A_END = DAY_1 + timedelta(days=29)  # Day 1's own window end (2026-08-30)
_LOW_ZONE_START = _HIGH_ZONE_A_END + timedelta(days=1)  # 2026-08-31
_LOW_ZONE_END = DAY_2 + timedelta(days=29)  # Day 2's own window end (2026-10-04)
_HIGH_ZONE_B_START = _LOW_ZONE_END + timedelta(days=1)  # 2026-10-05
_HIGH_ZONE_B_END = DAY_3 + timedelta(days=29)  # Day 3's own window end (2026-11-08)

_HIGH_OTA, _HIGH_DIRECT = 90, 10  # 90% OTA: comfortably >= the 70% structural threshold
_LOW_OTA, _LOW_DIRECT = 20, 80  # 20% OTA: comfortably below both the 55%/70% thresholds
_TOTAL = _HIGH_OTA + _HIGH_DIRECT  # == _LOW_OTA + _LOW_DIRECT == 100


def _weeks_back(anchor: date, count: int) -> list[date]:
    return [anchor - timedelta(weeks=k) for k in range(1, count + 1)]


@dataclass
class LifecycleOtaWorld:
    """One dedicated REV_OTA_DEPENDENCY source: real bookings across three non-overlapping
    calendar zones, real snapshots at every as-of this scenario evaluates or compares against."""

    session: Session
    tenant: Tenant

    def evaluate(self, as_of_local_date: date) -> OtaDependencyEvaluation:
        return OtaDependencyService(self.session, self.tenant.context).evaluate(
            property_id=self.tenant.property.id,
            booking_data_source_id=self.tenant.data_source.id,
            as_of_local_date=as_of_local_date,
        )


def build_lifecycle_ota_world(
    session: Session, factory: BookingFactory, tenant: Tenant
) -> LifecycleOtaWorld:
    """A SEPARATE `REV_OTA_DEPENDENCY` source on the SAME property as the shared golden world
    (nothing here reuses the canonical OTA source's calendar range or channels)."""
    source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    lifecycle_tenant = Tenant(tenant.workspace, tenant.property, source, factory.import_job(source))
    world = DistributionWorld(session, lifecycle_tenant, factory)

    ota_channel = world.channel("Lifecycle OTA", channel_type=ChannelType.OTA, is_verified=True)
    direct_channel = world.channel(
        "Lifecycle Direct", channel_type=ChannelType.DIRECT, is_verified=True
    )

    world.uniform_bookings(
        _HIGH_ZONE_A_START,
        _HIGH_ZONE_A_END,
        [(ota_channel, _HIGH_OTA), (direct_channel, _HIGH_DIRECT)],
    )
    world.uniform_bookings(
        _LOW_ZONE_START, _LOW_ZONE_END, [(ota_channel, _LOW_OTA), (direct_channel, _LOW_DIRECT)]
    )
    world.uniform_bookings(
        _HIGH_ZONE_B_START,
        _HIGH_ZONE_B_END,
        [(ota_channel, _HIGH_OTA), (direct_channel, _HIGH_DIRECT)],
    )

    # Every as-of this scenario ever evaluates OR uses as a historical comparable (each target's
    # own 6 weekly comparables, Gate 9's own rule): one 30-night `snapshot_window` per as-of. The
    # total is always 100 - only the OTA/DIRECT split (driven by the real bookings above) differs.
    as_of_dates = {
        DAY_1,
        DAY_2,
        DAY_3,
        *_weeks_back(DAY_1, 6),
        *_weeks_back(DAY_2, 6),
        *_weeks_back(DAY_3, 6),
    }
    for as_of in as_of_dates:
        world.snapshot_window(as_of, as_of, as_of + timedelta(days=29), _TOTAL)

    return LifecycleOtaWorld(session, lifecycle_tenant)


@dataclass
class DecisionGoldenWorld:
    priority_world: PriorityGoldenWorld
    lifecycle_ota: LifecycleOtaWorld

    @property
    def tenant(self) -> Tenant:
        return self.priority_world.tenant


def build_decision_golden_world(session: Session, factory: BookingFactory) -> DecisionGoldenWorld:
    priority_world = build_priority_golden_world(session, factory)
    lifecycle_ota = build_lifecycle_ota_world(session, factory, priority_world.tenant)
    session.commit()
    return DecisionGoldenWorld(priority_world, lifecycle_ota)


__all__ = [
    "DAY_1",
    "DAY_2",
    "DAY_3",
    "DecisionGoldenWorld",
    "LifecycleOtaWorld",
    "build_decision_golden_world",
    "build_lifecycle_ota_world",
]
