from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.validation import Name, Sha256Hex
from app.modules.ingestion.models import DataSourceDomain, DataSourceType, ImportJobStatus

Filename = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class DataSourceCreate(BaseModel):
    # No workspace_id: it always comes from the TenantContext, never from the payload.
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    name: Name
    domain: DataSourceDomain
    source_type: DataSourceType = DataSourceType.FILE_UPLOAD


class DataSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    property_id: UUID
    name: str
    domain: DataSourceDomain
    source_type: DataSourceType
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ImportJobCreate(BaseModel):
    """The property is not sent: it is always the data source's own property."""

    model_config = ConfigDict(extra="forbid")

    data_source_id: UUID


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    status: ImportJobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class ImportFileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: Filename
    mime_type: Annotated[str, StringConstraints(max_length=255)] | None = None
    size_bytes: Annotated[int, Field(ge=0)] | None = None
    sha256: Sha256Hex | None = None
    storage_key: Annotated[str, StringConstraints(max_length=1024)] | None = None


class ImportFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    import_job_id: UUID
    original_filename: str
    mime_type: str | None
    size_bytes: int | None
    sha256: str | None
    storage_key: str | None
    created_at: datetime
