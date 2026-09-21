"""PostgreSQL advisory locks shared by the services that must not overlap.

Only transaction-scoped locks are used: they are released by COMMIT or ROLLBACK and can never
outlive a request, so there is no lock leak and no distributed-locking machinery. They are
per-database (single PostgreSQL), which is exactly the V1 deployment.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_data_source(session: Session, data_source_id: UUID) -> None:
    """Serialise, for ONE data source, the writers of its canonical data and its snapshot runs.

    Held until the current transaction ends. The booking import takes it for its canonical
    write and the snapshot services take it for their whole calculation, so a snapshot never
    sees a half-written import and two runs on the same source never interleave.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": str(data_source_id)},
    )


def lock_supplier_registry(session: Session, workspace_id: UUID) -> None:
    """Serialise, for ONE workspace, the writers of its supplier registry.

    A supplier belongs to the workspace and is shared by all its data sources, so two invoice
    imports of different data sources could otherwise both create the same new supplier. Held until
    the current transaction ends; always taken AFTER the data-source lock (a fixed order, so two
    imports can never deadlock on the pair).
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": f"suppliers:{workspace_id}"},
    )
