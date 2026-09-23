"""Tenant-scoped, READ-ONLY access to the canonical labor entries for LABOR_OVERSTAFFING V1.

ONE statement returns, for every work date a target evaluation needs (the target day itself and
every historical candidate day), every `LaborEntry` of a snapshot with `snapshot_local_date <=`
the target's own as-of date. `latest_snapshot_rows_by_work_date` (pure, `aggregation.py`) then
picks, per work date, the most recent such snapshot: a rolling near-term export and a full-horizon
export are both handled correctly, with no query per day.

It reads `labor_entries`/`labor_snapshots` only: never the staging rows, never a file. The
repository never writes.
"""

from collections.abc import Collection
from datetime import date
from uuid import UUID

from sqlalchemy import Date, column, select, values
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.labor.aggregation import RawLaborEntryRow
from app.modules.labor.models import LaborEntry, LaborSnapshot

_KEYS_PER_QUERY = 5000


class LaborEvaluationRepository:
    """Labor entries of ONE workspace, read for the LABOR_OVERSTAFFING detector."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def entries_as_of(
        self, data_source_id: UUID, as_of_date: date, work_dates: Collection[date]
    ) -> list[RawLaborEntryRow]:
        """Every entry of `data_source_id` whose snapshot is `<= as_of_date`, restricted to the
        given work dates. ONE statement (a join with a VALUES list of the wanted dates)."""
        if not work_dates:
            return []
        ordered = sorted(set(work_dates))
        found: list[RawLaborEntryRow] = []
        for start in range(0, len(ordered), _KEYS_PER_QUERY):
            block = ordered[start : start + _KEYS_PER_QUERY]
            wanted = values(column("work_date", Date), name="wanted").data([(d,) for d in block])
            rows = self._session.execute(
                select(
                    LaborEntry.labor_snapshot_id,
                    LaborSnapshot.snapshot_local_date,
                    LaborEntry.work_date,
                    LaborEntry.labor_category,
                    LaborEntry.planned_minutes,
                    LaborEntry.actual_minutes,
                    LaborEntry.planned_cost,
                    LaborEntry.actual_cost,
                    LaborEntry.currency,
                    LaborEntry.classification_confidence,
                )
                .join(
                    LaborSnapshot,
                    (LaborEntry.workspace_id == LaborSnapshot.workspace_id)
                    & (LaborEntry.labor_snapshot_id == LaborSnapshot.id),
                )
                .join(wanted, LaborEntry.work_date == wanted.c.work_date)
                .where(
                    LaborEntry.workspace_id == self._tenant.workspace_id,
                    LaborSnapshot.data_source_id == data_source_id,
                    LaborSnapshot.snapshot_local_date <= as_of_date,
                )
            )
            found.extend(RawLaborEntryRow(*row) for row in rows)
        return found
