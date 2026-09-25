"""DB-side concurrency defences: uniqueness and tenant integrity (tests 130, 133).

Genuine two-thread concurrency (131, 132) needs REAL commits across separate sessions, which the
standard rolled-back `db_session` fixture cannot provide: see `test_decision_real_commits.py`.
"""

from datetime import date
from typing import Any

import psycopg
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.modules.decisions.identity import DecisionIdentity, build_identity
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from tests.decision_support import fp, revenue_evaluation
from tests.support import BookingFactory, Rejects, Tenant

STAY = date(2026, 8, 15)
D1 = date(2026, 8, 1)


def _decision_values(
    tenant: Tenant, identity: DecisionIdentity, **overrides: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "decision_type": identity.decision_type,
        "identity_version": "decision-identity-v1",
        "identity_key": identity.identity_key,
        "identity_payload": identity.identity_payload,
        "status": "OPEN",
        "first_seen_local_date": D1,
        "last_seen_local_date": D1,
        "last_evaluated_local_date": D1,
        "resolved_local_date": None,
        "episode_count": 1,
        "triggered_observation_count": 1,
    }
    values.update(overrides)
    return values


def test_duplicate_identity_is_prevented_db_side(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    identity = build_identity(evaluation)
    db_session.execute(insert(Decision), _decision_values(tenant, identity))

    with rejects(
        psycopg.errors.UniqueViolation,
        "uq_decisions_property_id_decision_type_identity_key",
    ):
        db_session.execute(insert(Decision), _decision_values(tenant, identity))


def test_a_decision_cannot_point_at_another_workspaces_property(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    identity = build_identity(evaluation)
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            insert(Decision),
            _decision_values(tenant, identity, property_id=other.property.id),
        )


def test_a_decision_run_cannot_point_at_another_workspaces_property(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            insert(DecisionRun),
            {
                "workspace_id": tenant.workspace.id,
                "property_id": other.property.id,
                "as_of_local_date": D1,
                "input_fingerprint": fp("run"),
                "priority_ranking_fingerprint": fp("ranking"),
                "evaluation_count": 0,
                "triggered_count": 0,
                "clear_count": 0,
                "insufficient_count": 0,
                "not_applicable_count": 0,
                "suppressed_count": 0,
                "duplicate_input_count": 0,
            },
        )


def test_an_observation_cannot_point_at_another_workspaces_decision(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=other.workspace.id,
        property_id=other.property.id,
        data_source_id=other.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    foreign_identity = build_identity(evaluation)
    foreign_decision_id = db_session.execute(
        insert(Decision).returning(Decision.id),
        _decision_values(
            other, foreign_identity, workspace_id=other.workspace.id, property_id=other.property.id
        ),
    ).scalar_one()

    run_id = db_session.execute(
        insert(DecisionRun).returning(DecisionRun.id),
        {
            "workspace_id": tenant.workspace.id,
            "property_id": tenant.property.id,
            "as_of_local_date": D1,
            "input_fingerprint": fp("run2"),
            "priority_ranking_fingerprint": fp("ranking2"),
            "evaluation_count": 0,
            "triggered_count": 0,
            "clear_count": 0,
            "insufficient_count": 0,
            "not_applicable_count": 0,
            "suppressed_count": 0,
            "duplicate_input_count": 0,
        },
    ).scalar_one()

    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            insert(DecisionObservation),
            {
                "workspace_id": tenant.workspace.id,  # tenant's own workspace
                "decision_id": foreign_decision_id,  # but the Decision belongs to `other`
                "decision_run_id": run_id,
                "property_id": tenant.property.id,
                "as_of_local_date": D1,
                "source_status": "TRIGGERED",
                "lifecycle_transition": "OPENED",
                "source_evaluation_fingerprint": fp("eval"),
                "source_target_key": "stay:2026-08-15|snapshot:x",
                "priority_candidate_fingerprint": fp("candidate"),
                "priority_rank": 1,
                "impact_score": "80.00",
                "urgency_score": "80.00",
                "confidence_score": "80.00",
                "actionability_score": "90.00",
                "priority_score": "82.00",
                "source_reason_codes": [],
                "facts_payload": {},
                "evidence_payload": {},
                "memory_version": "decision-memory-v1",
                "observation_fingerprint": fp("observation"),
            },
        )
