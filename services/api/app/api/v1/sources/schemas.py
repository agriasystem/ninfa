"""Wire shapes of the data-source API V1. Enums travel as plain strings (the page never needs the
Python enum); nothing here carries a file name, a file content (beyond the few preview cells the
caller just sent) or a technical error message."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
