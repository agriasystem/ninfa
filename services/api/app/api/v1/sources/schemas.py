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
from app.modules.data_sources.understanding import UnderstandAnswers
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


class ChoiceResponse(BaseModel):
    value: str
    count: int | None
    sheets: list[str]
    columns: list[str]
    title: str | None = None
    first_row: int | None = None


class LabelCountResponse(BaseModel):
    label: str
    count: int


class QuestionResponse(BaseModel):
    id: str
    kind: str
    column: str | None
    field: str | None
    document: str | None
    candidate: str | None
    origin: str | None
    choices: list[ChoiceResponse]
    labels: list[LabelCountResponse]
    total_labels: int


class BlockerResponse(BaseModel):
    code: str
    groups: list[list[str]]


class OriginResponse(BaseModel):
    kind: str
    detail: str | None


class RecognizedResponse(BaseModel):
    field: str
    origin: OriginResponse
    level: str
    example: str | None


class DomainScoreResponse(BaseModel):
    domain: str
    score: float


class DetectionResponse(BaseModel):
    domain: str | None
    level: str
    scores: list[DomainScoreResponse]
    expected: str | None


class SheetSummaryResponse(BaseModel):
    name: str
    role: str
    rows: int


class TableSummaryResponse(BaseModel):
    sheets: list[str]
    header_rows: list[int]
    first_row: int
    last_row: int
    data_rows: int
    partition: bool
    renamed_headers: int


class SkippedSummaryResponse(BaseModel):
    totals: int
    notes: int
    sections: int


class DocumentSummaryResponse(BaseModel):
    file_type: str
    sheets: list[SheetSummaryResponse]
    table: TableSummaryResponse | None
    title: str | None
    period_start: str | None
    period_end: str | None
    skipped: SkippedSummaryResponse
    totals: str | None
    day_grid: bool
    amounts: str | None = None


class UnderstandingResponse(BaseModel):
    level: str
    detection: DetectionResponse
    document: DocumentSummaryResponse
    recognized: list[RecognizedResponse]
    people: int | None
    questions: list[QuestionResponse]
    blockers: list[BlockerResponse]


class DryRunSummaryResponse(BaseModel):
    date_from: str | None
    date_to: str | None
    departments: list[str]
    planned_hours: str | None
    actual_hours: str | None
    planned_cost: str | None
    actual_cost: str | None
    currency: str | None
    channels: int | None
    revenue: str | None
    documents: int | None
    suppliers: int | None
    net_total: str | None


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
    # Smart Import V3 (only on `import-understanding`): what NINFA understood of the DOCUMENT and
    # the decision it proposes from that.
    understanding: UnderstandingResponse | None = None
    proposal: MappingInput | None = None


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
    rows_unclassified: int
    summary: DryRunSummaryResponse | None = None
    questions: list[QuestionResponse] = Field(default_factory=list)


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
    # The first day of the period THIS file is about (a grid of days written Lun/Mar/...).
    period_start: date | None = None

    def content(self) -> bytes:
        try:
            return base64.b64decode(self.file_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidImportRequestError() from error


class UnderstandRequest(BaseModel):
    """A file, the kind of data it should be read as, and what the person has already said."""

    model_config = ConfigDict(extra="forbid")

    domain: DataSourceDomain
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(max_length=MAX_JSON_BODY_BYTES)
    # The person already said this is the kind of data (do not ask again).
    confirmed_domain: bool = False
    answers: UnderstandAnswers = Field(default_factory=UnderstandAnswers)

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
    "UnderstandRequest",
    "UnderstandingResponse",
    "DryRunSummaryResponse",
    "QuestionResponse",
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
