import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check

if TYPE_CHECKING:
    from app.modules.ingestion.models import DataSource, ImportFile
    from app.modules.properties.models import Property

# Money: NUMERIC(12, 2) holds up to 9,999,999,999.99 in the property's currency (no FX in V1).
# Values with more than two decimals are rejected by the importer, never silently rounded.
MONEY_PRECISION, MONEY_SCALE = 12, 2
MAX_MONEY = Decimal("9999999999.99")
# Percentages (commission rates) allow four decimals: NUMERIC(7, 4), range-checked to 0..100.
RATE_PRECISION, RATE_SCALE = 7, 4


class BookingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class ChannelType(StrEnum):
    DIRECT = "DIRECT"
    OTA = "OTA"
    TOUR_OPERATOR = "TOUR_OPERATOR"
    AGENCY = "AGENCY"
    CORPORATE = "CORPORATE"
    OTHER = "OTHER"


class ImportRowStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    IMPORTED = "IMPORTED"


class BookingChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A distribution channel of ONE property ("Booking.com" of property A is not that of B:
    contracts and commissions differ). Created unverified as OTHER unless something explicit
    says otherwise.
    """

    __tablename__ = "booking_channels"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_type: Mapped[ChannelType] = mapped_column(
        enum_column(ChannelType, 16),
        nullable=False,
        default=ChannelType.OTHER,
        server_default=ChannelType.OTHER.value,
    )
    default_commission_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE)
    )
    is_verified: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )

    property: Mapped["Property"] = relationship("Property", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_booking_channels_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        # One channel per normalised name and property (also serves "channels of a property").
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "normalized_name",
            name="uq_booking_channels_workspace_id_property_id_normalized_name",
        ),
        # Target of bookings' composite FK: a booking's channel belongs to the booking's property.
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "id",
            name="uq_booking_channels_workspace_id_property_id_id",
        ),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(normalized_name) <> ''", name="normalized_name_not_blank"),
        CheckConstraint(values_check("channel_type", ChannelType), name="channel_type_valid"),
        CheckConstraint(
            "default_commission_rate IS NULL OR default_commission_rate BETWEEN 0 AND 100",
            name="default_commission_rate_range",
        ),
    )


class BookingMappingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The confirmed way to read one data source's files ("mapping memory"). One current profile
    per data source. Holds configuration only, never file content.
    """

    __tablename__ = "booking_mapping_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    channel_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    format_options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    header_signature: Mapped[str] = mapped_column(String(64), nullable=False)

    data_source: Mapped["DataSource"] = relationship("DataSource", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_booking_mapping_profiles_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name="uq_booking_mapping_profiles_workspace_id_data_source_id",
        ),
        CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(status_mapping) = 'object'"
            " AND jsonb_typeof(channel_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name="json_shapes",
        ),
        CheckConstraint("header_signature ~ '^[0-9a-f]{64}$'", name="header_signature_format"),
    )


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The canonical booking: one row per booking of a source system.

    Identity is (workspace_id, data_source_id, source_record_id); `id` is NINFA's own UUID.
    Tenant integrity is carried by composite foreign keys, all including workspace_id and
    property_id: to the data source, to the channel and to the first/last import job (which
    must also belong to the booking's own data source).
    """

    __tablename__ = "bookings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)

    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(enum_column(BookingStatus, 16), nullable=False)

    rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    guests: Mapped[int | None] = mapped_column(Integer)

    room_revenue: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False
    )
    total_revenue: Mapped[Decimal | None] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    channel_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(RATE_PRECISION, RATE_SCALE))

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    room_type: Mapped[str | None] = mapped_column(String(200))
    rate_plan: Mapped[str | None] = mapped_column(String(200))

    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    last_import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    data_source: Mapped["DataSource"] = relationship("DataSource", viewonly=True)
    channel: Mapped["BookingChannel"] = relationship("BookingChannel", viewonly=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_bookings_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "channel_id"],
            [
                "booking_channels.workspace_id",
                "booking_channels.property_id",
                "booking_channels.id",
            ],
            name="fk_bookings_workspace_id_booking_channels",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "first_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name="fk_bookings_first_import_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "last_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name="fk_bookings_last_import_job",
            ondelete="RESTRICT",
        ),
        # The identity of a booking inside its source system: the basis of idempotent imports.
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            "source_record_id",
            name="uq_bookings_workspace_id_data_source_id_source_record_id",
        ),
        CheckConstraint("btrim(source_record_id) <> ''", name="source_record_id_not_blank"),
        CheckConstraint(values_check("status", BookingStatus), name="status_valid"),
        CheckConstraint("check_out > check_in", name="check_out_after_check_in"),
        CheckConstraint("rooms > 0", name="rooms_positive"),
        CheckConstraint("guests IS NULL OR guests > 0", name="guests_positive"),
        CheckConstraint("room_revenue >= 0", name="room_revenue_non_negative"),
        CheckConstraint(
            "total_revenue IS NULL OR total_revenue >= 0", name="total_revenue_non_negative"
        ),
        CheckConstraint(
            "commission_amount IS NULL OR commission_amount >= 0",
            name="commission_amount_non_negative",
        ),
        CheckConstraint(
            "commission_rate IS NULL OR commission_rate BETWEEN 0 AND 100",
            name="commission_rate_range",
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR status = 'CANCELLED'", name="cancelled_at_requires_cancelled"
        ),
        CheckConstraint("room_type IS NULL OR btrim(room_type) <> ''", name="room_type_not_blank"),
        CheckConstraint("rate_plan IS NULL OR btrim(rate_plan) <> ''", name="rate_plan_not_blank"),
        CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="source_fingerprint_format"),
        # Stay-date range queries of a property: the core access path of hospitality data.
        Index(
            "ix_bookings_workspace_id_property_id_check_in",
            "workspace_id",
            "property_id",
            "check_in",
        ),
        Index(
            "ix_bookings_workspace_id_property_id_status", "workspace_id", "property_id", "status"
        ),
    )


class BookingImportRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Staging of one source row of a booking import.

    Data minimisation: `mapped_payload` holds ONLY the values of columns that were explicitly
    mapped to canonical fields (keyed by canonical field, as text). The rest of the source row
    (guest names, e-mails, phones, notes, ...) is never stored. `validation_errors` carries
    field names and stable codes, not values.
    """

    __tablename__ = "booking_import_rows"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mapped_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # none_as_null: Python None must be SQL NULL (rows without a normalised form), not JSON null.
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    validation_status: Mapped[ImportRowStatus] = mapped_column(
        enum_column(ImportRowStatus, 16), nullable=False
    )
    validation_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    import_file: Mapped["ImportFile"] = relationship("ImportFile", viewonly=True)

    __table_args__ = (
        # One key pins the file to the job *and* the job to the workspace (the file's own FK
        # already ties file -> job -> workspace).
        ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name="fk_booking_import_rows_workspace_id_import_files",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "row_number",
            name="uq_booking_import_rows_workspace_id_import_file_id_row_number",
        ),
        CheckConstraint("row_number > 0", name="row_number_positive"),
        CheckConstraint(values_check("validation_status", ImportRowStatus), name="status_valid"),
        CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name="payload_shapes",
        ),
        CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name="status_consistent",
        ),
        # Rows of a job (diagnostics and canonicalisation read them by job).
        Index("ix_booking_import_rows_workspace_id_import_job_id", "workspace_id", "import_job_id"),
    )
