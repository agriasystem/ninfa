"""ORM models of Decision Persistence, Lifecycle and Memory V1 (migration `0009_decision_layer`).

Three tables, in dependency order:

    decision_runs          one Decision Layer sync of a workspace/property/as-of/input
                            (APPEND-ONLY: a trigger refuses UPDATE)
    decisions               the persistent identity + CURRENT lifecycle state of one operational
                            problem (MUTABLE: this is the one row a lifecycle rule updates)
    decision_observations   one immutable memory of what a run knew about one Decision
                            (APPEND-ONLY: a trigger refuses UPDATE)

`Decision` is deliberately thin: identity + current status + lifecycle counters/dates. It never
duplicates the facts of its latest Observation - history lives entirely in
`decision_observations` (see docs/architecture/decision-layer-v1.md, "Decision current row").
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.decisions.types import DecisionStatus, LifecycleTransition, SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType

CONFIDENCE_PRECISION, CONFIDENCE_SCALE = 5, 2


class DecisionRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One Decision Layer sync of ONE workspace/property/as-of/logical input.

    Append-only (a trigger refuses UPDATE): auditable, idempotent (the unique key below is what
    makes an exact replay return the SAME row) and the anchor every Observation of this run
    points back to. A run with zero TRIGGERED evaluations is a perfectly valid row.
    """

    __tablename__ = "decision_runs"

    # A DB-generated, strictly increasing run sequence: `created_at` alone (a `timestamptz` server
    # default) cannot break a tie between two runs of the same transaction, and PostgreSQL's
    # `now()` is fixed for the whole transaction block, not per statement - two runs synced back
    # to back inside one transaction would otherwise share an identical `created_at`. This is the
    # "stable run order" `docs/architecture/decision-layer-v1.md`'s Memory Order section asks for,
    # used ONLY to order `decision_observations` history - never business logic, never exposed
    # outside this module.
    run_sequence: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True, start=1), nullable=False
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    as_of_local_date: Mapped[date] = mapped_column(Date, nullable=False)

    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    priority_ranking_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_count: Mapped[int] = mapped_column(Integer, nullable=False)
    clear_count: Mapped[int] = mapped_column(Integer, nullable=False)
    insufficient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    not_applicable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_input_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_decision_runs_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_decision_runs_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "as_of_local_date",
            "input_fingerprint",
            name="uq_decision_runs_property_id_as_of_local_date_input_fingerprint",
        ),
        UniqueConstraint("run_sequence", name="uq_decision_runs_run_sequence"),
        CheckConstraint(
            "evaluation_count >= 0 AND triggered_count >= 0 AND clear_count >= 0"
            " AND insufficient_count >= 0 AND not_applicable_count >= 0"
            " AND suppressed_count >= 0 AND duplicate_input_count >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "evaluation_count = triggered_count + clear_count + insufficient_count"
            " + not_applicable_count + suppressed_count",
            name="evaluation_count_is_sum",
        ),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="input_fingerprint_format",
        ),
        CheckConstraint(
            "priority_ranking_fingerprint ~ '^[0-9a-f]{64}$'",
            name="priority_ranking_fingerprint_format",
        ),
    )


class Decision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The persistent identity of ONE operational problem, plus its CURRENT lifecycle state.

    MUTABLE by design (unlike its Observations): `status`, the three dates, `resolved_local_date`
    and the two counters are updated in place by the lifecycle rules. Identity columns
    (`decision_type`, `identity_version`, `identity_key`, `identity_payload`) never change once
    written - nothing here updates them, and there is no code path that would.
    """

    __tablename__ = "decisions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    decision_type: Mapped[PriorityDecisionType] = mapped_column(
        enum_column(PriorityDecisionType, 32), nullable=False
    )
    identity_version: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    status: Mapped[DecisionStatus] = mapped_column(enum_column(DecisionStatus, 10), nullable=False)

    first_seen_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_evaluated_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    resolved_local_date: Mapped[date | None] = mapped_column(Date)

    episode_count: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_observation_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_decisions_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_decisions_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "decision_type",
            "identity_key",
            name="uq_decisions_property_id_decision_type_identity_key",
        ),
        Index(
            "ix_decisions_workspace_id_property_id_status",
            "workspace_id",
            "property_id",
            "status",
        ),
        Index(
            "ix_decisions_workspace_id_property_id_decision_type",
            "workspace_id",
            "property_id",
            "decision_type",
        ),
        CheckConstraint(
            values_check("decision_type", PriorityDecisionType), name="decision_type_valid"
        ),
        CheckConstraint(values_check("status", DecisionStatus), name="status_valid"),
        CheckConstraint("btrim(identity_version) <> ''", name="identity_version_not_blank"),
        CheckConstraint("identity_key ~ '^[0-9a-f]{64}$'", name="identity_key_format"),
        CheckConstraint(
            "jsonb_typeof(identity_payload) = 'object'", name="identity_payload_is_object"
        ),
        CheckConstraint("episode_count >= 1", name="episode_count_positive"),
        CheckConstraint(
            "triggered_observation_count >= 1", name="triggered_observation_count_positive"
        ),
        CheckConstraint(
            "(status = 'OPEN' AND resolved_local_date IS NULL)"
            " OR (status = 'RESOLVED' AND resolved_local_date IS NOT NULL)",
            name="resolved_date_matches_status",
        ),
        CheckConstraint(
            "first_seen_local_date <= last_seen_local_date", name="first_seen_before_last_seen"
        ),
        CheckConstraint(
            "first_seen_local_date <= last_evaluated_local_date",
            name="first_seen_before_last_evaluated",
        ),
        CheckConstraint(
            "last_seen_local_date <= last_evaluated_local_date",
            name="last_seen_before_last_evaluated",
        ),
        CheckConstraint(
            "resolved_local_date IS NULL OR resolved_local_date >= first_seen_local_date",
            name="resolved_not_before_first_seen",
        ),
        CheckConstraint(
            "resolved_local_date IS NULL OR resolved_local_date <= last_evaluated_local_date",
            name="resolved_not_after_last_evaluated",
        ),
    )


class DecisionObservation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One IMMUTABLE memory of what a `DecisionRun` knew about one `Decision` (a trigger refuses
    UPDATE). `priority_*` fields are populated only for `source_status = TRIGGERED`: they are the
    ONE PriorityCandidate Gate 10 already produced for this evaluation, copied - never
    recomputed, never overwritten by a later, different-day ranking of the same Decision.
    """

    __tablename__ = "decision_observations"

    decision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    as_of_local_date: Mapped[date] = mapped_column(Date, nullable=False)

    source_status: Mapped[SourceStatus] = mapped_column(
        enum_column(SourceStatus, 32), nullable=False
    )
    lifecycle_transition: Mapped[LifecycleTransition] = mapped_column(
        enum_column(LifecycleTransition, 20), nullable=False
    )

    source_evaluation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_target_key: Mapped[str] = mapped_column(String(512), nullable=False)

    priority_candidate_fingerprint: Mapped[str | None] = mapped_column(String(64))
    priority_rank: Mapped[int | None] = mapped_column(Integer)

    # Unconstrained NUMERIC (no fixed precision/scale): impact_score/priority_score are computed
    # in the Priority Engine's dedicated 50-significant-digit `Decimal` context and can carry that
    # many digits (a threshold_progress ratio is not always terminating at two decimals); a fixed
    # scale would silently truncate the very value this table exists to keep exact.
    impact_score: Mapped[Decimal | None] = mapped_column(Numeric())
    urgency_score: Mapped[Decimal | None] = mapped_column(Numeric())
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(CONFIDENCE_PRECISION, CONFIDENCE_SCALE), nullable=False
    )
    actionability_score: Mapped[Decimal | None] = mapped_column(Numeric())
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric())

    source_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    facts_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    memory_version: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["decisions.workspace_id", "decisions.id"],
            name="fk_decision_observations_workspace_id_decisions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "decision_run_id"],
            ["decision_runs.workspace_id", "decision_runs.id"],
            name="fk_decision_observations_workspace_id_decision_runs",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_decision_observations_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "decision_id",
            "decision_run_id",
            name="uq_decision_observations_decision_id_decision_run_id",
        ),
        Index(
            "ix_decision_observations_decision_id_as_of_local_date",
            "workspace_id",
            "decision_id",
            "as_of_local_date",
        ),
        Index(
            "ix_decision_observations_decision_run_id",
            "workspace_id",
            "decision_run_id",
        ),
        CheckConstraint(values_check("source_status", SourceStatus), name="source_status_valid"),
        CheckConstraint(
            values_check("lifecycle_transition", LifecycleTransition),
            name="lifecycle_transition_valid",
        ),
        CheckConstraint(
            "source_evaluation_fingerprint ~ '^[0-9a-f]{64}$'",
            name="source_evaluation_fingerprint_format",
        ),
        CheckConstraint("btrim(source_target_key) <> ''", name="source_target_key_not_blank"),
        CheckConstraint(
            "priority_candidate_fingerprint IS NULL"
            " OR priority_candidate_fingerprint ~ '^[0-9a-f]{64}$'",
            name="priority_candidate_fingerprint_format",
        ),
        CheckConstraint(
            "priority_rank IS NULL OR priority_rank >= 1", name="priority_rank_positive"
        ),
        CheckConstraint("confidence_score BETWEEN 0 AND 100", name="confidence_score_range"),
        CheckConstraint(
            "(source_status = 'TRIGGERED' AND priority_candidate_fingerprint IS NOT NULL"
            " AND priority_rank IS NOT NULL AND impact_score IS NOT NULL"
            " AND urgency_score IS NOT NULL AND actionability_score IS NOT NULL"
            " AND priority_score IS NOT NULL)"
            " OR (source_status <> 'TRIGGERED' AND priority_candidate_fingerprint IS NULL"
            " AND priority_rank IS NULL AND impact_score IS NULL AND urgency_score IS NULL"
            " AND actionability_score IS NULL AND priority_score IS NULL)",
            name="priority_fields_match_source_status",
        ),
        CheckConstraint(
            "jsonb_typeof(source_reason_codes) = 'array'", name="source_reason_codes_is_array"
        ),
        CheckConstraint("jsonb_typeof(facts_payload) = 'object'", name="facts_payload_is_object"),
        CheckConstraint(
            "jsonb_typeof(evidence_payload) = 'object'", name="evidence_payload_is_object"
        ),
        CheckConstraint("btrim(memory_version) <> ''", name="memory_version_not_blank"),
        CheckConstraint(
            "observation_fingerprint ~ '^[0-9a-f]{64}$'", name="observation_fingerprint_format"
        ),
    )


__all__ = ["Decision", "DecisionObservation", "DecisionRun"]
