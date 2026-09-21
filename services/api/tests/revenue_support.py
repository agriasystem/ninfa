"""Helpers shared by the Gate 5 (Revenue Decision Detection) tests. Synthetic data only.

Two families: PURE builders (snapshot points, pairs, selections, target contexts) for the
detectors, and a DB world that stores real snapshots and a real Gate 4 baseline.
"""

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.intelligence.revenue.pairing import SnapshotKey
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import (
    HistoricalPair,
    PairProvenance,
    PairSelection,
    SnapshotPoint,
    TargetContext,
)
from app.modules.snapshots.models import SnapshotOrigin
from tests.expected_support import (
    ELIGIBLE,
    LEAD,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    add_snapshots,
    snapshot_row,
)
from tests.support import BookingFactory, Tenant

OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
OBSERVED_PAIR = PairProvenance.OBSERVED_PAIR
APPROXIMATE_PAIR = PairProvenance.APPROXIMATE_PAIR


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


__all__ = [
    "APPROXIMATE_PAIR",
    "ELIGIBLE",
    "LEAD",
    "OBSERVED",
    "OBSERVED_PAIR",
    "RECONSTRUCTED",
    "TARGET_SNAPSHOT_DAY",
    "TARGET_STAY",
    "RevenueWorld",
    "make_pair",
    "make_selection",
    "statements_of",
    "pickup_selection",
    "point",
    "remaining_selection",
    "target_context",
]

_NEWEST_STAY = date(2026, 7, 25)


# --- pure builders --------------------------------------------------------------------------


def point(
    snapshot_day: date,
    stay: date,
    rooms: int,
    *,
    origin: SnapshotOrigin = OBSERVED,
    uncertain: int = 0,
    adr: Decimal | None = Decimal("100.00"),
) -> SnapshotPoint:
    return SnapshotPoint(
        snapshot_id=uuid.uuid4(),
        snapshot_local_date=snapshot_day,
        stay_date=stay,
        origin=origin,
        rooms_on_books=rooms,
        uncertain_rooms=uncertain,
        adr_on_books=adr if rooms > 0 else None,
    )


def endpoints_of(*points: SnapshotPoint) -> dict[SnapshotKey, SnapshotPoint]:
    return {(p.snapshot_local_date, p.stay_date): p for p in points}


def make_pair(
    index: int,
    anchor_rooms: int,
    other_rooms: int,
    *,
    provenance: PairProvenance = OBSERVED_PAIR,
    delta: int | None = None,
) -> HistoricalPair:
    """A curve pair of the stay date `index` weeks before 2026-07-25 (index 0 = newest)."""
    stay = _NEWEST_STAY - timedelta(days=7 * index)
    approximate = provenance == APPROXIMATE_PAIR
    anchor = point(stay - timedelta(days=14), stay, anchor_rooms)
    other = point(
        stay,
        stay,
        other_rooms,
        origin=RECONSTRUCTED if approximate else OBSERVED,
    )
    return HistoricalPair(
        stay_date=stay,
        anchor=anchor,
        other=other,
        provenance=provenance,
        delta=other_rooms - anchor_rooms if delta is None else delta,
    )


def make_selection(pairs: Sequence[HistoricalPair], **counts: int) -> PairSelection:
    observed = sum(p.provenance == OBSERVED_PAIR for p in pairs)
    return PairSelection(
        pairs=tuple(pairs),
        observed_pair_count=observed,
        approximate_pair_count=len(pairs) - observed,
        rejected_uncertain_count=counts.get("rejected_uncertain_count", 0),
        missing_endpoint_count=counts.get("missing_endpoint_count", 0),
        excluded_future_count=counts.get("excluded_future_count", 0),
    )


def pickup_selection(pickups: Sequence[int], *, approximate: Sequence[int] = ()) -> PairSelection:
    """Pairs whose historical pickup (anchor - prior) are `pickups`, newest pair first."""
    pairs = [
        make_pair(
            index,
            anchor_rooms=20,
            other_rooms=20 - pickup,
            provenance=APPROXIMATE_PAIR if index in approximate else OBSERVED_PAIR,
            delta=pickup,
        )
        for index, pickup in enumerate(pickups)
    ]
    return make_selection(pairs)


def remaining_selection(
    remaining: Sequence[int], finals: Sequence[int], *, approximate: Sequence[int] = ()
) -> PairSelection:
    """Pairs whose remaining net pickup (final - anchor) are `remaining`, with these finals."""
    pairs = [
        make_pair(
            index,
            anchor_rooms=final - rest,
            other_rooms=final,
            provenance=APPROXIMATE_PAIR if index in approximate else OBSERVED_PAIR,
            delta=rest,
        )
        for index, (rest, final) in enumerate(zip(remaining, finals, strict=True))
    ]
    return make_selection(pairs)


def target_context(
    *,
    rooms: int = 20,
    available: int | None = 40,
    adr: Decimal | None = Decimal("100.00"),
    baseline_status: ExpectedStatus | None = ExpectedStatus.READY,
    baseline_confidence: Decimal | None = Decimal("90.00"),
    snapshot_day: date = TARGET_SNAPSHOT_DAY,
    stay: date = TARGET_STAY,
    baseline_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
) -> TargetContext:
    has_baseline = baseline_status is not None
    return TargetContext(
        workspace_id=uuid.UUID(int=1),
        property_id=uuid.UUID(int=2),
        data_source_id=uuid.UUID(int=3),
        target_snapshot_id=target_id or uuid.UUID(int=4),
        snapshot_local_date=snapshot_day,
        stay_date=stay,
        rooms_on_books=rooms,
        rooms_available=available,
        adr_on_books=adr,
        baseline_id=(baseline_id or uuid.UUID(int=5)) if has_baseline else None,
        baseline_status=baseline_status,
        baseline_confidence=baseline_confidence if has_baseline else None,
    )


# --- a real database world ------------------------------------------------------------------


def snap(
    tenant: Tenant,
    snapshot_day: date,
    stay: date,
    rooms: int,
    *,
    origin: SnapshotOrigin = OBSERVED,
    uncertain: int = 0,
    adr: Decimal = Decimal("100.00"),
    available: int | None = None,
    data_source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """A valid snapshot row with a controllable ADR and capacity (occupancy kept consistent)."""
    row = snapshot_row(
        tenant,
        snapshot_day,
        stay,
        rooms=rooms,
        origin=origin,
        uncertain_rooms=uncertain,
        data_source_id=data_source_id,
    )
    row["adr_on_books"] = adr if rooms > 0 else None
    row["allocated_room_revenue_on_books"] = adr * rooms
    row["rooms_available"] = available
    if available is not None and available > 0:
        row["occupancy_on_books"] = (Decimal(rooms) * 100 / Decimal(available)).quantize(
            Decimal("0.01")
        )
    return row


@dataclass
class RevenueWorld:
    """One tenant, an OBSERVED target snapshot and a controllable history of curve endpoints.

    The default target is Saturday 2026-08-15 seen 14 days before (snapshot day 2026-08-01), the
    same target the Gate 4 tests use; its Expected baseline is calculated by the REAL Gate 4
    service on the stored comparables, never inserted by hand.
    """

    session: Session
    tenant: Tenant
    target_id: uuid.UUID
    rows: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        session: Session,
        factory: BookingFactory,
        *,
        target_rooms: int = 12,
        available: int | None = None,
        adr: Decimal = Decimal("100.00"),
        tenant: Tenant | None = None,
    ) -> "RevenueWorld":
        tenant = tenant or factory.tenant()
        row = snap(
            tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, target_rooms, adr=adr, available=available
        )
        add_snapshots(session, tenant, [row])
        return cls(session, tenant, row["id"], [row])

    def add(self, *rows: dict[str, Any]) -> None:
        add_snapshots(self.session, self.tenant, list(rows))
        self.rows.extend(rows)

    def own_prior(
        self, rooms: int, *, origin: SnapshotOrigin = OBSERVED, adr: Decimal = Decimal("100.00")
    ) -> uuid.UUID:
        """The target's own snapshot 7 snapshot days earlier (same stay date)."""
        row = snap(
            self.tenant,
            TARGET_SNAPSHOT_DAY - timedelta(days=7),
            TARGET_STAY,
            rooms,
            origin=origin,
            adr=adr,
        )
        self.add(row)
        return row["id"]  # type: ignore[no-any-return]

    def curve(
        self,
        stay: date,
        *,
        prior: int | None,
        anchor: int,
        final: int | None,
        prior_origin: SnapshotOrigin = OBSERVED,
        anchor_origin: SnapshotOrigin = OBSERVED,
        final_origin: SnapshotOrigin = OBSERVED,
        prior_uncertain: int = 0,
        anchor_uncertain: int = 0,
        final_uncertain: int = 0,
        anchor_adr: Decimal = Decimal("100.00"),
        lead: int = LEAD,
    ) -> uuid.UUID:
        """Store the curve of ONE historical stay date: the snapshot 7 days before the anchor,
        the anchor (`lead` days before the stay date) and the final one (on the stay date).
        `None` leaves an endpoint missing. Returns the anchor snapshot id."""
        anchor_row = snap(
            self.tenant,
            stay - timedelta(days=lead),
            stay,
            anchor,
            origin=anchor_origin,
            uncertain=anchor_uncertain,
            adr=anchor_adr,
        )
        rows = [anchor_row]
        if prior is not None:
            rows.append(
                snap(
                    self.tenant,
                    stay - timedelta(days=lead + 7),
                    stay,
                    prior,
                    origin=prior_origin,
                    uncertain=prior_uncertain,
                )
            )
        if final is not None:
            rows.append(
                snap(
                    self.tenant,
                    stay,
                    stay,
                    final,
                    origin=final_origin,
                    uncertain=final_uncertain,
                )
            )
        self.add(*rows)
        return anchor_row["id"]  # type: ignore[no-any-return]

    def curves(
        self,
        stays: Sequence[date],
        *,
        prior: Sequence[int] | int,
        anchor: Sequence[int] | int,
        final: Sequence[int] | int,
        **kwargs: Any,
    ) -> None:
        """Many curves at once; a scalar is repeated for every stay date."""

        def pick(value: Sequence[int] | int, index: int) -> int:
            return value if isinstance(value, int) else value[index]

        for index, stay in enumerate(stays):
            self.curve(
                stay,
                prior=pick(prior, index),
                anchor=pick(anchor, index),
                final=pick(final, index),
                **kwargs,
            )

    # --- the services ---------------------------------------------------------------------

    def calculate(self, target_id: uuid.UUID | None = None) -> None:
        """Commit and run the REAL Gate 4 service for the target."""
        self.session.commit()
        BookingExpectedService(self.session, self.tenant.context).calculate_for_target(
            property_id=self.tenant.property.id,
            data_source_id=self.tenant.data_source.id,
            target_snapshot_id=target_id or self.target_id,
        )

    def baseline(self, target_id: uuid.UUID | None = None) -> BookingExpectedBaseline:
        found = ExpectedRepository(self.session, self.tenant.context).get_for_target_snapshot(
            target_id or self.target_id
        )
        assert found is not None
        return found

    def service(self) -> RevenueDecisionService:
        return RevenueDecisionService(self.session, self.tenant.context)
