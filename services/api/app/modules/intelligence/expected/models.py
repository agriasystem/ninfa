import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.confidence import ConfidenceBand
from app.modules.snapshots.models import SnapshotOrigin

# Expected rooms are medians/quartiles of integers: multiples of 0.25, exact with two decimals.
ROOMS_PRECISION, ROOMS_SCALE = 12, 2
CONFIDENCE_PRECISION, CONFIDENCE_SCALE = 5, 2


class BookingExpectedBaseline(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """What was NORMALLY on the books for comparable stays, for ONE observed target snapshot.

    An immutable, auditable record (no `updated_at`, a trigger refuses UPDATE): the comparables
    it rests on are the rows of `booking_expected_comparables`. `READY` carries the statistics
    and a confidence band; `INSUFFICIENT_DATA` carries NO number at all (a median of too few
    comparables is not an Expected) and a confidence of 0 without a band.

    This is a historical level, not a forecast: it says nothing about how the stay will end.
    """

    __tablename__ = "booking_expected_baselines"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    target_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Part of the composite FK to the snapshot: the database itself guarantees the target is an
    # OBSERVED snapshot of the same workspace, property and data source.
    target_origin: Mapped[SnapshotOrigin] = mapped_column(
        enum_column(SnapshotOrigin, 32), nullable=False
    )
    target_snapshot_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_stay_date: Mapped[date] = mapped_column(Date, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[ExpectedStatus] = mapped_column(enum_column(ExpectedStatus, 20), nullable=False)
    expected_rooms_on_books: Mapped[Decimal | None] = mapped_column(
        Numeric(ROOMS_PRECISION, ROOMS_SCALE)
    )
    expected_lower: Mapped[Decimal | None] = mapped_column(Numeric(ROOMS_PRECISION, ROOMS_SCALE))
    expected_upper: Mapped[Decimal | None] = mapped_column(Numeric(ROOMS_PRECISION, ROOMS_SCALE))
    iqr: Mapped[Decimal | None] = mapped_column(Numeric(ROOMS_PRECISION, ROOMS_SCALE))

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    reconstructed_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_uncertain_count: Mapped[int] = mapped_column(Integer, nullable=False)

    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(CONFIDENCE_PRECISION, CONFIDENCE_SCALE), nullable=False
    )
    confidence_band: Mapped[ConfidenceBand | None] = mapped_column(enum_column(ConfidenceBand, 8))

    method: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    comparable_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_booking_expected_baselines_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_booking_expected_baselines_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        # The target snapshot belongs to the baseline's own workspace, property and data source,
        # and is an OBSERVED one (target_origin is CHECKed to 'OBSERVED' below).
        ForeignKeyConstraint(
            [
                "workspace_id",
                "property_id",
                "data_source_id",
                "target_snapshot_id",
                "target_origin",
            ],
            [
                "booking_snapshots.workspace_id",
                "booking_snapshots.property_id",
                "booking_snapshots.data_source_id",
                "booking_snapshots.id",
                "booking_snapshots.origin",
            ],
            name="fk_booking_expected_baselines_target_snapshot",
            ondelete="RESTRICT",
        ),
        # One baseline per target and calculation version (the immutability key; also the
        # "baseline of this snapshot" lookup).
        UniqueConstraint(
            "workspace_id",
            "target_snapshot_id",
            "calculation_version",
            name="uq_booking_expected_baselines_target_version",
        ),
        # Target of the comparables' foreign key: a comparable shares the baseline's source.
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "data_source_id",
            "id",
            name="uq_booking_expected_baselines_ws_prop_src_id",
        ),
        Index(
            "ix_booking_expected_baselines_snapshot_date",
            "workspace_id",
            "data_source_id",
            "target_snapshot_local_date",
        ),
        Index(
            "ix_booking_expected_baselines_stay_date",
            "workspace_id",
            "data_source_id",
            "target_stay_date",
        ),
        CheckConstraint(values_check("status", ExpectedStatus), name="status_valid"),
        CheckConstraint(
            "confidence_band IS NULL OR " + values_check("confidence_band", ConfidenceBand),
            name="confidence_band_valid",
        ),
        CheckConstraint("target_origin = 'OBSERVED'", name="target_is_observed"),
        CheckConstraint("lead_time_days >= 0", name="lead_time_non_negative"),
        CheckConstraint(
            "lead_time_days = target_stay_date - target_snapshot_local_date",
            name="lead_time_matches_dates",
        ),
        CheckConstraint(
            "sample_size >= 0 AND observed_sample_size >= 0 AND reconstructed_sample_size >= 0"
            " AND rejected_uncertain_count >= 0",
            name="sample_counts_non_negative",
        ),
        CheckConstraint(
            "sample_size = observed_sample_size + reconstructed_sample_size",
            name="sample_size_is_sum",
        ),
        CheckConstraint("confidence_score BETWEEN 0 AND 100", name="confidence_score_range"),
        CheckConstraint(
            "(expected_rooms_on_books IS NULL OR expected_rooms_on_books >= 0)"
            " AND (expected_lower IS NULL OR expected_lower >= 0)"
            " AND (expected_upper IS NULL OR expected_upper >= 0)"
            " AND (iqr IS NULL OR iqr >= 0)",
            name="statistics_non_negative",
        ),
        CheckConstraint(
            "expected_lower IS NULL OR (expected_lower <= expected_rooms_on_books"
            " AND expected_rooms_on_books <= expected_upper)",
            name="range_ordered",
        ),
        CheckConstraint(
            "iqr IS NULL OR iqr = expected_upper - expected_lower", name="iqr_is_range_width"
        ),
        # READY: every statistic, a band and at least 5 comparables (the V1 minimum sample).
        CheckConstraint(
            "status <> 'READY' OR (expected_rooms_on_books IS NOT NULL"
            " AND expected_lower IS NOT NULL AND expected_upper IS NOT NULL AND iqr IS NOT NULL"
            " AND confidence_band IS NOT NULL AND sample_size >= 5)",
            name="ready_has_statistics",
        ),
        # INSUFFICIENT_DATA: NO number, confidence 0 without a band, fewer than 5 comparables.
        CheckConstraint(
            "status <> 'INSUFFICIENT_DATA' OR (expected_rooms_on_books IS NULL"
            " AND expected_lower IS NULL AND expected_upper IS NULL AND iqr IS NULL"
            " AND confidence_score = 0 AND confidence_band IS NULL AND sample_size < 5)",
            name="insufficient_has_no_statistics",
        ),
        CheckConstraint("btrim(method) <> ''", name="method_not_blank"),
        CheckConstraint("btrim(calculation_version) <> ''", name="calculation_version_not_blank"),
        CheckConstraint(
            "comparable_fingerprint ~ '^[0-9a-f]{64}$'", name="comparable_fingerprint_format"
        ),
    )


class BookingExpectedComparable(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One historical snapshot a baseline actually used (explains "why did NINFA expect 17.5?").

    `rooms_on_books` and `origin` are copies of the snapshot's; the composite foreign keys keep
    the comparable in the baseline's workspace, property and data source, and `origin` equal to
    the snapshot's. `recency_rank` 1 is the most recent comparable stay date.
    """

    __tablename__ = "booking_expected_comparables"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    origin: Mapped[SnapshotOrigin] = mapped_column(enum_column(SnapshotOrigin, 32), nullable=False)
    rooms_on_books: Mapped[int] = mapped_column(Integer, nullable=False)
    recency_rank: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "baseline_id"],
            [
                "booking_expected_baselines.workspace_id",
                "booking_expected_baselines.property_id",
                "booking_expected_baselines.data_source_id",
                "booking_expected_baselines.id",
            ],
            name="fk_booking_expected_comparables_baseline",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "snapshot_id", "origin"],
            [
                "booking_snapshots.workspace_id",
                "booking_snapshots.property_id",
                "booking_snapshots.data_source_id",
                "booking_snapshots.id",
                "booking_snapshots.origin",
            ],
            name="fk_booking_expected_comparables_snapshot",
            ondelete="RESTRICT",
        ),
        # A snapshot is a comparable of a baseline at most once (its prefix also serves "the
        # comparables of a baseline", so no separate index exists for that).
        UniqueConstraint(
            "workspace_id",
            "baseline_id",
            "snapshot_id",
            name="uq_booking_expected_comparables_baseline_snapshot",
        ),
        UniqueConstraint(
            "workspace_id",
            "baseline_id",
            "recency_rank",
            name="uq_booking_expected_comparables_baseline_rank",
        ),
        CheckConstraint(values_check("origin", SnapshotOrigin), name="origin_valid"),
        CheckConstraint("rooms_on_books >= 0", name="rooms_on_books_non_negative"),
        CheckConstraint("recency_rank >= 1", name="recency_rank_positive"),
    )
