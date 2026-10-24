"""PostgreSQL advisory locks shared by the services that must not overlap.

Only transaction-scoped locks are used: they are released by COMMIT or ROLLBACK and can never
outlive a request, so there is no lock leak and no distributed-locking machinery. They are
per-database (single PostgreSQL), which is exactly the V1 deployment.

One lock is held by a transaction of its OWN (`hold_source_import_lock`): the work it protects
commits several times, and a lock taken on the work's own transaction would be released by the first
commit. It is still a transaction-scoped lock - it dies with that transaction, or with its
connection if the process dies.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

_LOCK_NOT_AVAILABLE = "55P03"  # PostgreSQL: the lock was not granted within `lock_timeout`


class LockWaitTimeoutError(Exception):
    """A lock could not be taken within the wait the caller allowed."""


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


def lock_decision_layer(session: Session, workspace_id: UUID, property_id: UUID) -> None:
    """Serialise, for ONE workspace/property, concurrent Decision Layer syncs.

    Held until the current transaction ends. Two processes syncing the same property at once must
    never both decide "no Decision exists for this identity yet" and each create one: this lock
    makes their lifecycle mutations line up behind each other. The unique key on
    `(workspace_id, property_id, decision_type, identity_key)` remains the last line of defence.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": f"decisions:{workspace_id}:{property_id}"},
    )


def source_import_lock_key(workspace_id: UUID, property_id: UUID, domain: str) -> str:
    """The name `hold_source_import_lock` locks (hashed by PostgreSQL), one per workspace / property
    / kind of data."""
    return f"source-import:{workspace_id}:{property_id}:{domain}"


@contextmanager
def hold_source_import_lock(
    session: Session, workspace_id: UUID, property_id: UUID, domain: str, *, wait_ms: int
) -> Iterator[None]:
    """Let ONE file import at a time run for a workspace / property / kind of data.

    The decision "this property has no source of this kind yet, create one" is a check followed by
    a write: two first imports arriving together would both see no source and both create one. This
    lock makes the second wait until the first has finished completely - source created, file
    imported, source switched off again if the import failed - and then see the state it left.

    The lock is taken on a connection of its own, in a transaction of its own, and that transaction
    stays open until the block exits: the import commits several times on the caller's session, so
    a lock on that session would be gone after the first commit. Different properties, different
    kinds of data and different workspaces use different keys and never wait for each other. The
    lock is PostgreSQL's, so it holds across every API worker and process.

    Taken BEFORE `lock_data_source` and `lock_supplier_registry` (a fixed order: the import takes
    those inside the block), so the three can never deadlock on each other. Raises
    `LockWaitTimeoutError` if the lock is not granted within `wait_ms`.
    """
    key = source_import_lock_key(workspace_id, property_id, domain)
    with session.get_bind().engine.connect() as connection, connection.begin():
        connection.execute(
            text("SELECT set_config('lock_timeout', :wait, true)"), {"wait": f"{wait_ms}ms"}
        )
        try:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
                {"key": key},
            )
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE:
                raise LockWaitTimeoutError(key) from error
            raise
        yield


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
