"""Read schemas of the bookings module (the future API shape; no Create schemas: bookings are
written only by the import, never directly by a client).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.bookings.models import BookingStatus, ChannelType, ImportRowStatus


class BookingChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    property_id: UUID
    name: str
    normalized_name: str
    channel_type: ChannelType
    default_commission_rate: Decimal | None
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    source_record_id: str
    booked_at: datetime
    check_in: date
    check_out: date
    status: BookingStatus
    rooms: int
    guests: int | None
    room_revenue: Decimal
    total_revenue: Decimal | None
    channel_id: UUID
    commission_amount: Decimal | None
    commission_rate: Decimal | None
    cancelled_at: datetime | None
    room_type: str | None
    rate_plan: str | None
    source_fingerprint: str
    first_import_job_id: UUID
    last_import_job_id: UUID
    created_at: datetime
    updated_at: datetime


class BookingMappingProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    column_mapping: dict[str, Any]
    status_mapping: dict[str, Any]
    channel_mapping: dict[str, Any]
    format_options: dict[str, Any]
    header_signature: str
    created_at: datetime
    updated_at: datetime


class BookingImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    import_job_id: UUID
    import_file_id: UUID
    row_number: int
    mapped_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    validation_status: ImportRowStatus
    validation_errors: list[dict[str, str]]
    created_at: datetime
