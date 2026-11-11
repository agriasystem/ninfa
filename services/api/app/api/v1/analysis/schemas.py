from datetime import datetime

from pydantic import BaseModel


class AnalysisStatusResponse(BaseModel):
    """Where the analysis stands against the data: a descriptor beside the feed, which keeps its own
    four states. `can_retry` is the backend's: the page never works out what may be asked again."""

    state: str
    imported_domains: list[str]
    latest_import_at: datetime | None
    last_analysis_at: datetime | None
    next_attempt_at: datetime | None
    can_retry: bool
