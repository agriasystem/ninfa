"""Gate 11: Decision Persistence, Lifecycle and Memory V1.

Adds three tables:

    decision_runs           one Decision Layer sync of a workspace/property/as-of/logical input
                              (append-only: idempotency and audit anchor for every Observation)
    decisions                the persistent CROSS-DAY identity of an operational problem, plus its
                              CURRENT lifecycle state (OPEN/RESOLVED, dates, episode counters) -
                              the only MUTABLE row of the three
    decision_observations    one immutable memory of what a run knew about one Decision (source
                              status, lifecycle transition, the Priority snapshot when TRIGGERED,
                              explicit per-detector facts/evidence)

Tenant integrity (see ADR 0006), composite foreign keys carrying workspace_id, all RESTRICT:

    decision_runs           (workspace, property)                    -> properties
    decisions                (workspace, property)                    -> properties
    decision_observations    (workspace, decision)                    -> decisions
    decision_observations    (workspace, decision_run)                -> decision_runs
    decision_observations    (workspace, property)                    -> properties

`decision_runs` and `decision_observations` are immutable evidence: a trigger refuses every
UPDATE, exactly like Gate 8's labor snapshots/entries. `decisions` is deliberately mutable: it is
the CURRENT state of a lifecycle, updated in place by `DecisionService.sync()` (never a full
history - that lives in `decision_observations`). DELETE is not blocked: the foreign keys are
RESTRICT and retention belongs to a later gate.

Written by hand; `tests/test_data_model_migration.py` keeps the ORM metadata in sync with it.
Migrations 0001-0008 are untouched (Gates 5, 7, 9, 10 added no schema; the head before this gate
was `0008_labor_ingestion`).

Revision ID: 0009_decision_layer
Revises: 0008_labor_ingestion
Create Date: 2026-09-24
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_decision_layer"
down_revision: str | None = "0008_labor_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DECISION_TYPES = (
    "'REV_PICKUP_LOW', 'REV_OCCUPANCY_RISK', 'REV_OTA_DEPENDENCY', 'COST_CPOR_ANOMALY',"
    " 'LABOR_OVERSTAFFING'"
)
DECISION_STATUSES = "'OPEN', 'RESOLVED'"
SOURCE_STATUSES = (
    "'TRIGGERED', 'CLEAR', 'INSUFFICIENT_DATA', 'NOT_APPLICABLE', 'SUPPRESSED_LOW_CONFIDENCE'"
)
LIFECYCLE_TRANSITIONS = "'OPENED', 'OBSERVED', 'RESOLVED', 'REOPENED', 'NO_STATE_CHANGE'"


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


_IMMUTABLE_FUNCTION = """
CREATE FUNCTION decisions_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'decisions: a decision run and its observations are immutable memory'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # --- decision_runs -------------------------------------------------------------------------
    op.create_table(
        "decision_runs",
        _id(),
        sa.Column(
            "run_sequence",
            sa.BigInteger(),
            sa.Identity(always=True, start=1),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("as_of_local_date", sa.Date(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("priority_ranking_fingerprint", sa.String(64), nullable=False),
        sa.Column("evaluation_count", sa.Integer(), nullable=False),
        sa.Column("triggered_count", sa.Integer(), nullable=False),
        sa.Column("clear_count", sa.Integer(), nullable=False),
        sa.Column("insufficient_count", sa.Integer(), nullable=False),
        sa.Column("not_applicable_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_input_count", sa.Integer(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_runs")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_decision_runs_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_decision_runs_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "as_of_local_date",
            "input_fingerprint",
            name=op.f("uq_decision_runs_property_id_as_of_local_date_input_fingerprint"),
        ),
        sa.UniqueConstraint("run_sequence", name=op.f("uq_decision_runs_run_sequence")),
        sa.CheckConstraint(
            "evaluation_count >= 0 AND triggered_count >= 0 AND clear_count >= 0"
            " AND insufficient_count >= 0 AND not_applicable_count >= 0"
            " AND suppressed_count >= 0 AND duplicate_input_count >= 0",
            name=op.f("ck_decision_runs_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "evaluation_count = triggered_count + clear_count + insufficient_count"
            " + not_applicable_count + suppressed_count",
            name=op.f("ck_decision_runs_evaluation_count_is_sum"),
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_decision_runs_input_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "priority_ranking_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_decision_runs_priority_ranking_fingerprint_format"),
        ),
    )

    # --- decisions -------------------------------------------------------------------------------
    op.create_table(
        "decisions",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("decision_type", sa.String(32), nullable=False),
        sa.Column("identity_version", sa.String(32), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("identity_payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("first_seen_local_date", sa.Date(), nullable=False),
        sa.Column("last_seen_local_date", sa.Date(), nullable=False),
        sa.Column("last_evaluated_local_date", sa.Date(), nullable=False),
        sa.Column("resolved_local_date", sa.Date(), nullable=True),
        sa.Column("episode_count", sa.Integer(), nullable=False),
        sa.Column("triggered_observation_count", sa.Integer(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_decisions_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_decisions_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "decision_type",
            "identity_key",
            name=op.f("uq_decisions_property_id_decision_type_identity_key"),
        ),
        sa.CheckConstraint(
            f"decision_type IN ({DECISION_TYPES})", name=op.f("ck_decisions_decision_type_valid")
        ),
        sa.CheckConstraint(
            f"status IN ({DECISION_STATUSES})", name=op.f("ck_decisions_status_valid")
        ),
        sa.CheckConstraint(
            "btrim(identity_version) <> ''", name=op.f("ck_decisions_identity_version_not_blank")
        ),
        sa.CheckConstraint(
            "identity_key ~ '^[0-9a-f]{64}$'", name=op.f("ck_decisions_identity_key_format")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(identity_payload) = 'object'",
            name=op.f("ck_decisions_identity_payload_is_object"),
        ),
        sa.CheckConstraint("episode_count >= 1", name=op.f("ck_decisions_episode_count_positive")),
        sa.CheckConstraint(
            "triggered_observation_count >= 1",
            name=op.f("ck_decisions_triggered_observation_count_positive"),
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND resolved_local_date IS NULL)"
            " OR (status = 'RESOLVED' AND resolved_local_date IS NOT NULL)",
            name=op.f("ck_decisions_resolved_date_matches_status"),
        ),
        sa.CheckConstraint(
            "first_seen_local_date <= last_seen_local_date",
            name=op.f("ck_decisions_first_seen_before_last_seen"),
        ),
        sa.CheckConstraint(
            "first_seen_local_date <= last_evaluated_local_date",
            name=op.f("ck_decisions_first_seen_before_last_evaluated"),
        ),
        sa.CheckConstraint(
            "last_seen_local_date <= last_evaluated_local_date",
            name=op.f("ck_decisions_last_seen_before_last_evaluated"),
        ),
        sa.CheckConstraint(
            "resolved_local_date IS NULL OR resolved_local_date >= first_seen_local_date",
            name=op.f("ck_decisions_resolved_not_before_first_seen"),
        ),
        sa.CheckConstraint(
            "resolved_local_date IS NULL OR resolved_local_date <= last_evaluated_local_date",
            name=op.f("ck_decisions_resolved_not_after_last_evaluated"),
        ),
    )
    op.create_index(
        op.f("ix_decisions_workspace_id_property_id_status"),
        "decisions",
        ["workspace_id", "property_id", "status"],
    )
    op.create_index(
        op.f("ix_decisions_workspace_id_property_id_decision_type"),
        "decisions",
        ["workspace_id", "property_id", "decision_type"],
    )

    # --- decision_observations -----------------------------------------------------------------
    op.create_table(
        "decision_observations",
        _id(),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("decision_run_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("as_of_local_date", sa.Date(), nullable=False),
        sa.Column("source_status", sa.String(32), nullable=False),
        sa.Column("lifecycle_transition", sa.String(20), nullable=False),
        sa.Column("source_evaluation_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_target_key", sa.String(512), nullable=False),
        sa.Column("priority_candidate_fingerprint", sa.String(64), nullable=True),
        sa.Column("priority_rank", sa.Integer(), nullable=True),
        sa.Column("impact_score", sa.Numeric(), nullable=True),
        sa.Column("urgency_score", sa.Numeric(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("actionability_score", sa.Numeric(), nullable=True),
        sa.Column("priority_score", sa.Numeric(), nullable=True),
        sa.Column("source_reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("facts_payload", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_payload", postgresql.JSONB(), nullable=False),
        sa.Column("memory_version", sa.String(32), nullable=False),
        sa.Column("observation_fingerprint", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_observations")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["decisions.workspace_id", "decisions.id"],
            name=op.f("fk_decision_observations_workspace_id_decisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "decision_run_id"],
            ["decision_runs.workspace_id", "decision_runs.id"],
            name=op.f("fk_decision_observations_workspace_id_decision_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_decision_observations_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "decision_id",
            "decision_run_id",
            name=op.f("uq_decision_observations_decision_id_decision_run_id"),
        ),
        sa.CheckConstraint(
            f"source_status IN ({SOURCE_STATUSES})",
            name=op.f("ck_decision_observations_source_status_valid"),
        ),
        sa.CheckConstraint(
            f"lifecycle_transition IN ({LIFECYCLE_TRANSITIONS})",
            name=op.f("ck_decision_observations_lifecycle_transition_valid"),
        ),
        sa.CheckConstraint(
            "source_evaluation_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_decision_observations_source_evaluation_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "btrim(source_target_key) <> ''",
            name=op.f("ck_decision_observations_source_target_key_not_blank"),
        ),
        sa.CheckConstraint(
            "priority_candidate_fingerprint IS NULL"
            " OR priority_candidate_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_decision_observations_priority_candidate_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "priority_rank IS NULL OR priority_rank >= 1",
            name=op.f("ck_decision_observations_priority_rank_positive"),
        ),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name=op.f("ck_decision_observations_confidence_score_range"),
        ),
        sa.CheckConstraint(
            "(source_status = 'TRIGGERED' AND priority_candidate_fingerprint IS NOT NULL"
            " AND priority_rank IS NOT NULL AND impact_score IS NOT NULL"
            " AND urgency_score IS NOT NULL AND actionability_score IS NOT NULL"
            " AND priority_score IS NOT NULL)"
            " OR (source_status <> 'TRIGGERED' AND priority_candidate_fingerprint IS NULL"
            " AND priority_rank IS NULL AND impact_score IS NULL AND urgency_score IS NULL"
            " AND actionability_score IS NULL AND priority_score IS NULL)",
            name=op.f("ck_decision_observations_priority_fields_match_source_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_reason_codes) = 'array'",
            name=op.f("ck_decision_observations_source_reason_codes_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(facts_payload) = 'object'",
            name=op.f("ck_decision_observations_facts_payload_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_payload) = 'object'",
            name=op.f("ck_decision_observations_evidence_payload_is_object"),
        ),
        sa.CheckConstraint(
            "btrim(memory_version) <> ''",
            name=op.f("ck_decision_observations_memory_version_not_blank"),
        ),
        sa.CheckConstraint(
            "observation_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_decision_observations_observation_fingerprint_format"),
        ),
    )
    op.create_index(
        op.f("ix_decision_observations_decision_id_as_of_local_date"),
        "decision_observations",
        ["workspace_id", "decision_id", "as_of_local_date"],
    )
    op.create_index(
        op.f("ix_decision_observations_decision_run_id"),
        "decision_observations",
        ["workspace_id", "decision_run_id"],
    )

    # --- immutability of the run/observation evidence -------------------------------------------
    op.execute(sa.text(_IMMUTABLE_FUNCTION))
    for table in ("decision_runs", "decision_observations"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table}"
                " FOR EACH ROW EXECUTE FUNCTION decisions_forbid_update()"
            )
        )


def downgrade() -> None:
    # Children first; the triggers go with their tables. Gate 0-8 objects are untouched.
    op.drop_table("decision_observations")
    op.drop_table("decisions")
    op.drop_table("decision_runs")
    op.execute(sa.text("DROP FUNCTION decisions_forbid_update()"))
