"""Dati overview (Dati UI V1): the deterministic, read-only data behind the "Dati" page.

See docs/architecture/data-ui-v1.md and ADR 0031. Entry point: `DataOverviewService`.
"""

from app.modules.data_overview.service import DataOverviewError, DataOverviewService
from app.modules.data_overview.types import DATA_OVERVIEW_VERSION, DataOverview

__all__ = ["DATA_OVERVIEW_VERSION", "DataOverview", "DataOverviewError", "DataOverviewService"]
