"""Decision syncs with REAL commits, separate sessions and concurrent transactions (tests 131,
132). Every other Gate 11 test runs inside one outer transaction; this module proves the
`workspace/property` advisory lock really serialises two concurrent syncs of the SAME identity
into one creation and one observation - never two Decisions. The rows it creates are deleted
afterwards, the same pattern as `test_expected_real_commits.py`/`test_snapshot_real_commits.py`.
"""

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionSyncResult
from app.modules.ingestion.models import DataSource, DataSourceDomain, DataSourceType
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.properties.models import Property
from app.modules.tenancy.models import Workspace
from tests.decision_support import revenue_evaluation

STAY = date(2026, 8, 15)
D1 = date(2026, 8, 1)
_FIXED_TARGET_SNAPSHOT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@dataclass
class Committed:
    engine: Engine
    workspace_id: uuid.UUID
    property_id: uuid.UUID
    data_source_id: uuid.UUID

    @property
    def tenant(self) -> TenantContext:
        return TenantContext(self.workspace_id)

    def session(self) -> Session:
        return Session(self.engine)  # a fresh session per use, default expire_on_commit=True

    def sync(self) -> DecisionSyncResult:
        evaluation = revenue_evaluation(
            workspace_id=self.workspace_id,
            property_id=self.property_id,
            data_source_id=self.data_source_id,
            stay_date=STAY,
            snapshot_local_date=D1,
            fingerprint="a" * 64,  # the SAME logical evaluation every call: one identity
            target_snapshot_id=_FIXED_TARGET_SNAPSHOT_ID,  # so both threads build BYTE-IDENTICAL
            # evaluations (a random target_snapshot_id would make their source_target_key, and so
            # their candidate/ranking/run fingerprints, differ between threads)
        )
        context = PriorityContext(self.workspace_id, self.property_id, D1)
        with self.session() as session:
            from app.modules.intelligence.priority.fingerprint import ranking_fingerprint
            from app.modules.intelligence.priority.types import (
                PRIORITY_RULES_VERSION,
                PriorityRankingResult,
                RankedPriorityCandidate,
            )
            from tests.decision_support import candidate_for

            candidate = candidate_for(evaluation)
            fingerprint = ranking_fingerprint(
                workspace_id=self.workspace_id,
                property_id=self.property_id,
                as_of_local_date=D1,
                ranked_candidates=(RankedPriorityCandidate(1, candidate),),
                excluded_clear_count=0,
                excluded_insufficient_count=0,
                excluded_not_applicable_count=0,
                excluded_suppressed_count=0,
                duplicate_input_count=0,
                priority_version=PRIORITY_RULES_VERSION,
            )
            ranking = PriorityRankingResult(
                workspace_id=self.workspace_id,
                property_id=self.property_id,
                as_of_local_date=D1,
                candidate_count=1,
                excluded_clear_count=0,
                excluded_insufficient_count=0,
                excluded_not_applicable_count=0,
                excluded_suppressed_count=0,
                duplicate_input_count=0,
                ranked_candidates=(RankedPriorityCandidate(1, candidate),),
                calculation_fingerprint=fingerprint,
            )
            return DecisionService(session, self.tenant).sync(context, ranking, [evaluation])

    def open_decisions(self) -> list[Decision]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(Decision).where(Decision.workspace_id == self.workspace_id)
                ).all()
            )

    def observation_count(self) -> int:
        with self.session() as session:
            return len(
                session.scalars(
                    select(DecisionObservation.id).where(
                        DecisionObservation.workspace_id == self.workspace_id
                    )
                ).all()
            )


def purge(engine: Engine, workspace_id: uuid.UUID) -> None:
    with Session(engine) as session:
        for model in (DecisionObservation, Decision, DecisionRun, DataSource, Property):
            session.execute(delete(model).where(model.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


@pytest.fixture
def committed(db_engine: Engine) -> Iterator[Committed]:
    with Session(db_engine) as session:
        workspace = Workspace(name="Real Decisions", slug=f"real-decisions-{uuid.uuid4().hex[:10]}")
        session.add(workspace)
        session.flush()
        prop = Property(workspace_id=workspace.id, name="Hotel", slug="hotel")
        session.add(prop)
        session.flush()
        source = DataSource(
            workspace_id=workspace.id,
            property_id=prop.id,
            name="Bookings file",
            domain=DataSourceDomain.BOOKINGS,
            source_type=DataSourceType.FILE_UPLOAD,
        )
        session.add(source)
        session.flush()
        ids = Committed(db_engine, workspace.id, prop.id, source.id)
        session.commit()
    try:
        yield ids
    finally:
        purge(db_engine, ids.workspace_id)


def advisory_lock_is_free(engine: Engine, workspace_id: uuid.UUID, property_id: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:k AS text), 0))"),
                {"k": f"decisions:{workspace_id}:{property_id}"},
            ).scalar_one()
        )


def test_a_committed_decision_is_visible_to_other_sessions_and_releases_its_lock(
    committed: Committed,
) -> None:
    result = committed.sync()

    assert result.created_decision_count == 1
    assert len(committed.open_decisions()) == 1
    assert advisory_lock_is_free(committed.engine, committed.workspace_id, committed.property_id)


def test_two_concurrent_syncs_of_the_same_identity_create_one_decision(
    committed: Committed,
) -> None:
    barrier = threading.Barrier(2)

    def worker() -> DecisionSyncResult:
        barrier.wait(timeout=10)
        return committed.sync()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(worker), pool.submit(worker)]]

    # both threads submit the exact same logical input: the advisory lock serialises them so
    # exactly one CREATES (OPENED) and the other, finding the identical run already persisted,
    # is an idempotent replay - never two Decisions, whichever thread wins the race.
    open_decisions = committed.open_decisions()
    assert len(open_decisions) == 1  # never two Decisions for the same identity
    assert sorted(r.created_decision_count for r in results) == [0, 1]
    assert sorted(r.is_idempotent_replay for r in results) == [False, True]
    assert committed.observation_count() == 1  # the replay appended no second Observation
    assert advisory_lock_is_free(committed.engine, committed.workspace_id, committed.property_id)
