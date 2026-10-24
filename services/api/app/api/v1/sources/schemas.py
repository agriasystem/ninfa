"""Wire shapes of the data-source API V1. Enums travel as plain strings (the page never needs the
Python enum); nothing here carries a file name, a file content (beyond the few preview cells the
caller just sent) or a technical error message."""

import base64
import binascii
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.data_sources.errors import InvalidImportRequestError
from app.modules.data_sources.files import MAX_FILE_BYTES
from app.modules.data_sources.mapping_types import MappingInput
from app.modules.ingestion.models import DataSourceDomain


class SourceCardResponse(BaseModel):
    card: str
    state: str
    domain: str | None
    data_source_id: UUID | None
    method: str | None
    last_update_at: datetime | None
    several_sources: bool
    derived_from: str | None
    provider: str | None
    channels: list[str]


class CapabilityResponse(BaseModel):
    domain: str
    methods: list[str]


class SourcesOverviewResponse(BaseModel):
    property_id: UUID
    cards: list[SourceCardResponse]
    # How each kind of data can REALLY be provided today; nothing else is ever offered.
    capabilities: list[CapabilityResponse]
    # Real automatic integrations. Empty today, by design: nothing is simulated.
    automatic_integrations: list[str]


class ImportPreviewResponse(BaseModel):
    method: str
    can_import: bool
    problem: str | None
    rows_total: int
    recognized_columns: list[str]
    # Each entry is a group of alternatives, one of which the file must carry.
    missing_columns: list[list[str]]
    unrecognized_columns: list[str]
    sample_columns: list[str]
    sample_rows: list[list[str]]
    documents_with_issues: int
    already_imported: bool


class ImportResultResponse(BaseModel):
    succeeded: bool
    problem: str | None
    rows_total: int
    rows_invalid: int
    created: int
    updated: int
    unchanged: int
    already_imported: bool


# --- Smart Import: match the columns of the hotel own file ------------------------------


class ColumnInfoResponse(BaseModel):
    position: int
    header: str
    examples: list[str]
    field: str | None
    level: str | None
    not_used_reason: str | None
    date_order: str | None
    number_style: str | None


class ConstantSpecResponse(BaseModel):
    kind: str
    choices: list[str]
    default: str | int | None


class FieldSpecResponse(BaseModel):
    key: str
    kind: str
    constant: ConstantSpecResponse | None


class ProfileInfoResponse(BaseModel):
    status: str
    reason: str | None
    mapping: MappingInput | None
    last_used_at: datetime | None
    missing_columns: list[str]


class FileInspectionResponse(BaseModel):
    domain: str
    file_type: str | None
    problem: str | None
    sheet_name: str | None
    sheet_names: list[str]
    requires_sheet_selection: bool
    columns: list[ColumnInfoResponse]
    fields: list[FieldSpecResponse]
    # Each group is "at least one of"; a one-field group is a required field.
    requirement_groups: list[list[str]]
    suggestion_complete: bool
    already_canonical: bool
    profile: ProfileInfoResponse
    already_imported: bool


class MappingProblemResponse(BaseModel):
    code: str
    fields: list[str]


class MappingCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: DataSourceDomain
    mapping: MappingInput


class MappingCheckResponse(BaseModel):
    valid: bool
    missing: list[list[str]]
    problems: list[MappingProblemResponse]


class FormatHintResponse(BaseModel):
    question: str
    proven: str | None
    columns: list[str]


class RowProblemResponse(BaseModel):
    field: str
    code: str
    count: int


class RowIssueResponse(BaseModel):
    field: str
    code: str


class InvalidRowResponse(BaseModel):
    row: int
    issues: list[RowIssueResponse]


class DryRunResponse(BaseModel):
    status: str
    problem: str | None
    can_import: bool
    check: MappingCheckResponse | None
    format_hints: list[FormatHintResponse]
    rows_total: int
    rows_valid: int
    rows_invalid: int
    sample_fields: list[str]
    sample_rows: list[list[str | None]]
    row_problems: list[RowProblemResponse]
    invalid_rows: list[InvalidRowResponse]
    already_imported: bool


class SavedColumnResponse(BaseModel):
    field: str
    column: str


class SavedConstantResponse(BaseModel):
    field: str
    value: str


class SavedConfigurationResponse(BaseModel):
    data_source_id: str
    domain: str
    columns: list[SavedColumnResponse]
    constants: list[SavedConstantResponse]
    last_used_at: datetime | None
    schema_current: bool


# A file travels inside the JSON body as base64 (a mapping is structured data, and the API takes no
# multipart): the longest body is therefore a little over 4/3 of the largest file.
MAX_JSON_BODY_BYTES = MAX_FILE_BYTES * 4 // 3 + 64 * 1024


class MappedImportResultResponse(ImportResultResponse):
    # The way the columns were matched has been remembered for the next file of the same layout.
    configuration_saved: bool


class MappedFileRequest(BaseModel):
    """A file plus the person's matching of its columns - to try (dry run) or to import."""

    model_config = ConfigDict(extra="forbid")

    domain: DataSourceDomain
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(max_length=MAX_JSON_BODY_BYTES)
    # None: use the configuration saved for this kind of data.
    mapping: MappingInput | None = None

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.file_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidImportRequestError() from error


class MappedImportRequest(MappedFileRequest):
    # Remember the matching once the import has succeeded (only meaningful with a `mapping`).
    save_configuration: bool = False
    # Labor only: the property-local day the file is dated as of (YYYY-MM-DD).
    snapshot_local_date: date | None = None


__all__ = [
    "MAX_JSON_BODY_BYTES",
    "CapabilityResponse",
    "ColumnInfoResponse",
    "ConstantSpecResponse",
    "DryRunResponse",
    "FieldSpecResponse",
    "FileInspectionResponse",
    "FormatHintResponse",
    "ImportPreviewResponse",
    "ImportResultResponse",
    "InvalidRowResponse",
    "MappedFileRequest",
    "MappedImportRequest",
    "MappedImportResultResponse",
    "MappingCheckRequest",
    "MappingCheckResponse",
    "MappingProblemResponse",
    "ProfileInfoResponse",
    "RowIssueResponse",
    "RowProblemResponse",
    "SavedColumnResponse",
    "SavedConfigurationResponse",
    "SavedConstantResponse",
    "SourceCardResponse",
    "SourcesOverviewResponse",
]
