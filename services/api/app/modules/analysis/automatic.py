"""Automatic Analysis Policy (Gate 26B, Pilot Autonomy Gate): the rules, evaluated for one policy.

The rules (code, not per-property configuration):

* every property with its booking source is enrolled by itself once it has imported bookings
  (`enroll_ready_properties`); a policy switched off (`enabled = false`) stays off;
* the analysis looks at what a refresh looks at (`scope.analysis_request`): the 30 stay nights from
  the property-local today, labor and costs wherever the property really has them;
* it is due once per property-LOCAL day, from `DAILY_ANALYSIS_LOCAL_TIME` on, whatever the hour in
  UTC. The worker asks every few minutes (`worker.daily`), and being due is worked out from what is
  stored, never from when it last asked: a missed tick, a restart or a worker that was down only
  delays it, until the same local day's next tick;
* it runs whether or not someone imported today: the bookings NINFA holds are analysed, and the
  run's provenance says when they last arrived. An observation can be revised the same day
  (same-day-revisions-v1.md), so a file arriving later is analysed in its turn;
* at most one a day: a DecisionRun for today (from a refresh, an operator or this) means skip;
* a job that fails is asked again at most `MAX_DAILY_ATTEMPTS` times a day, `RETRY_AFTER` apart.

Two entry points share one evaluation: the dispatcher and the status read it (`evaluate_policy`),
and the policy task (`run_automatic_analysis`) evaluates again at execution time and then calls the
Gate 25 shared orchestration. This module contains no detector logic and no Procrastinate import.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.models import PropertyAnalysisPolicy
from app.modules.analysis.policy import (
    AnalysisPolicyError,
    AnalysisPolicyService,
    AutomaticSkipReason,
    check_configuration,
    list_enabled_policies,
)
from app.modules.analysis.queue import failed_policy_runs_since
from app.modules.analysis.scope import (
    AUTOMATIC_STAY_WINDOW_DAYS,
    analysis_request,
    automatic_stay_window,
)
from app.modules.analysis.service import AnalysisRunResult, run_property_analysis
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportJob,
    ImportJobStatus,
)
from app.modules.ingestion.repository import ImportJobRepository
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.localtime import local_date_of, local_day_start
from app.modules.tenancy.models import Workspace
from app.modules.tenancy.repository import WorkspaceRepository

# The hour the daily analysis is due, in the property's own time: the opportunity Gate 26B fixed. A
# file imported before it is analysed by its own refresh, which then counts as the day's run.
DAILY_ANALYSIS_LOCAL_TIME = time(10, 0)
MAX_DAILY_ATTEMPTS = 3
RETRY_AFTER = timedelta(hours=1)

_ANY_TIME = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """One enabled policy, evaluated at `evaluated_at`. `skip_reason` is None when eligible.
    The fact fields are None when the configuration blocked the evaluation before they could be
    known. `local_time` is what the property's clock says at that instant."""

    policy_id: UUID
    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID | None
    workspace_slug: str | None
    property_slug: str | None
    evaluated_at: datetime
    local_date: date | None
    run_exists_today: bool | None
    qualifying_import_today: bool | None
    latest_analysis_date: date | None
    skip_reason: AutomaticSkipReason | None
    local_time: time | None = None

    @property
    def eligible(self) -> bool:
        return self.skip_reason is None


def _latest_analysis_date(
    session: Session, tenant: TenantContext, property_id: UUID
) -> date | None:
    return session.scalar(
        select(func.max(DecisionRun.as_of_local_date)).where(
            DecisionRun.workspace_id == tenant.workspace_id, DecisionRun.property_id == property_id
        )
    )


def _run_exists_for(
    session: Session, tenant: TenantContext, property_id: UUID, local_date: date
) -> bool:
    return (
        session.scalar(
            select(DecisionRun.id)
            .where(
                DecisionRun.workspace_id == tenant.workspace_id,
                DecisionRun.property_id == property_id,
                DecisionRun.as_of_local_date == local_date,
            )
            .limit(1)
        )
        is not None
    )


def evaluate_policy(
    session: Session, policy: PropertyAnalysisPolicy, now: datetime
) -> PolicyEvaluation:
    """Re-validate the configuration and read today's facts, all as of the instant `now`."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("`now` must be a timezone-aware instant")
    now = now.astimezone(UTC)
    tenant = TenantContext(workspace_id=policy.workspace_id)

    workspace = WorkspaceRepository(session).get(policy.workspace_id)
    prop = PropertyRepository(session, tenant).get(policy.property_id)

    def result(
        reason: AutomaticSkipReason | None,
        local_date: date | None = None,
        run_today: bool | None = None,
        import_today: bool | None = None,
        latest: date | None = None,
        local_time: time | None = None,
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy_id=policy.id,
            workspace_id=policy.workspace_id,
            property_id=policy.property_id,
            booking_data_source_id=policy.booking_data_source_id,
            workspace_slug=None if workspace is None else workspace.slug,
            property_slug=None if prop is None else prop.slug,
            evaluated_at=now,
            local_date=local_date,
            run_exists_today=run_today,
            qualifying_import_today=import_today,
            latest_analysis_date=latest,
            skip_reason=reason,
            local_time=local_time,
        )

    if not policy.enabled:
        return result(AutomaticSkipReason.POLICY_DISABLED)

    check = check_configuration(
        session, policy.workspace_id, policy.property_id, policy.booking_data_source_id
    )
    local_date = None if check.timezone is None else local_date_of(now, check.timezone)
    if check.blocker is not None:
        return result(check.blocker, local_date)
    assert check.timezone is not None and local_date is not None
    assert policy.booking_data_source_id is not None

    run_today = _run_exists_for(session, tenant, policy.property_id, local_date)
    imports = ImportJobRepository(session, tenant)
    source_id = policy.booking_data_source_id
    import_today = imports.has_succeeded_between(
        source_id, local_day_start(local_date, check.timezone), now
    )
    latest = _latest_analysis_date(session, tenant, policy.property_id)

    reason: AutomaticSkipReason | None = None
    if run_today:
        reason = AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    elif not imports.has_succeeded_between(source_id, _ANY_TIME, now):
        reason = AutomaticSkipReason.NO_BOOKING_IMPORT
    return result(
        reason,
        local_date,
        run_today,
        import_today,
        latest,
        now.astimezone(check.timezone).time(),
    )


def evaluate_enabled_policies(session: Session, now: datetime) -> list[PolicyEvaluation]:
    """Every enabled policy of every workspace, evaluated at the SAME instant `now`."""
    return [evaluate_policy(session, policy, now) for policy in list_enabled_policies(session)]


def enroll_ready_properties(session: Session) -> tuple[UUID, ...]:
    """Switch the daily analysis on for every property ready for it that has never had a policy:
    active, with exactly ONE active booking file source with a successful import. Nobody has to ask
    for it.

    A policy that exists, enabled or not, is never touched: switching one off stays off. Several
    active booking sources are never chosen between. Platform-level like `list_enabled_policies`,
    and never reachable from an HTTP route: each enrolment then goes through the property's own
    `TenantContext`. Returns the properties enrolled."""
    candidates = session.execute(
        select(DataSource.workspace_id, DataSource.property_id, DataSource.id)
        .join(
            Property,
            (Property.workspace_id == DataSource.workspace_id)
            & (Property.id == DataSource.property_id),
        )
        .join(Workspace, Workspace.id == DataSource.workspace_id)
        .where(
            DataSource.domain == DataSourceDomain.BOOKINGS,
            DataSource.source_type == DataSourceType.FILE_UPLOAD,
            DataSource.is_active.is_(True),
            Property.is_active.is_(True),
            Property.archived_at.is_(None),
            Workspace.is_active.is_(True),
            Workspace.archived_at.is_(None),
            ~select(PropertyAnalysisPolicy.id)
            .where(PropertyAnalysisPolicy.property_id == DataSource.property_id)
            .exists(),
            select(ImportJob.id)
            .where(
                ImportJob.workspace_id == DataSource.workspace_id,
                ImportJob.data_source_id == DataSource.id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
            )
            .exists(),
        )
        .order_by(DataSource.workspace_id, DataSource.property_id, DataSource.id)
    ).all()
    by_property: dict[tuple[UUID, UUID], list[UUID]] = {}
    for workspace_id, property_id, source_id in candidates:
        by_property.setdefault((workspace_id, property_id), []).append(source_id)

    enrolled: list[UUID] = []
    for (workspace_id, property_id), sources in by_property.items():
        if len(sources) != 1:
            continue
        try:
            AnalysisPolicyService(session, TenantContext(workspace_id=workspace_id)).enable(
                property_id, sources[0]
            )
        except (AnalysisPolicyError, IntegrityError):  # its own check said no, or another got there
            session.rollback()
            continue
        enrolled.append(property_id)
    return tuple(enrolled)


def daily_opportunities(session: Session, now: datetime) -> list[PolicyEvaluation]:
    """Every enabled policy at the instant `now`, with the daily rules on top of the policy's own:
    not before the property's own `DAILY_ANALYSIS_LOCAL_TIME`, and not again after failing too often
    today."""
    opportunities: list[PolicyEvaluation] = []
    for evaluation in evaluate_enabled_policies(session, now):
        if not evaluation.eligible:
            opportunities.append(evaluation)
            continue
        assert evaluation.local_time is not None and evaluation.local_date is not None
        if evaluation.local_time < DAILY_ANALYSIS_LOCAL_TIME:
            opportunities.append(replace(evaluation, skip_reason=AutomaticSkipReason.NOT_DUE_YET))
            continue
        check = check_configuration(
            session,
            evaluation.workspace_id,
            evaluation.property_id,
            evaluation.booking_data_source_id,
        )
        assert check.timezone is not None
        failed, last_failed_at = failed_policy_runs_since(
            session,
            TenantContext(workspace_id=evaluation.workspace_id),
            evaluation.property_id,
            local_day_start(evaluation.local_date, check.timezone),
        )
        if failed >= MAX_DAILY_ATTEMPTS:
            reason: AutomaticSkipReason | None = AutomaticSkipReason.ATTEMPTS_EXHAUSTED
        elif last_failed_at is not None and now - last_failed_at < RETRY_AFTER:
            reason = AutomaticSkipReason.RETRY_NOT_DUE_YET
        else:
            reason = None
        opportunities.append(replace(evaluation, skip_reason=reason))
    return opportunities


class AutomaticOutcome(StrEnum):
    RAN = "RAN"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class AutomaticAnalysisOutcome:
    outcome: AutomaticOutcome
    skip_reason: AutomaticSkipReason | None
    local_date: date | None
    stay_date_start: date | None
    stay_date_end: date | None
    result: AnalysisRunResult | None


def run_automatic_analysis(
    session: Session, workspace_id: UUID, property_id: UUID, now: datetime | None = None
) -> AutomaticAnalysisOutcome:
    """Execute one automatic opportunity for a property: re-evaluate everything AT EXECUTION TIME
    (dates included), then either skip with a typed reason or run the shared orchestration on what
    the property really holds. A real failure propagates."""
    now = datetime.now(UTC) if now is None else now
    policy = session.scalar(
        select(PropertyAnalysisPolicy).where(
            PropertyAnalysisPolicy.workspace_id == workspace_id,
            PropertyAnalysisPolicy.property_id == property_id,
        )
    )
    if policy is None:
        return AutomaticAnalysisOutcome(
            AutomaticOutcome.SKIPPED, AutomaticSkipReason.POLICY_DISABLED, None, None, None, None
        )
    evaluation = evaluate_policy(session, policy, now)
    if not evaluation.eligible:
        return AutomaticAnalysisOutcome(
            AutomaticOutcome.SKIPPED,
            evaluation.skip_reason,
            evaluation.local_date,
            None,
            None,
            None,
        )
    assert evaluation.local_date is not None and policy.booking_data_source_id is not None
    request = analysis_request(
        session,
        TenantContext(workspace_id=workspace_id),
        property_id,
        policy.booking_data_source_id,
        evaluation.local_date,
    )
    result = run_property_analysis(session, request)
    return AutomaticAnalysisOutcome(
        AutomaticOutcome.RAN,
        None,
        evaluation.local_date,
        request.stay_date_start,
        request.stay_date_end,
        result,
    )


__all__ = [
    "AUTOMATIC_STAY_WINDOW_DAYS",
    "DAILY_ANALYSIS_LOCAL_TIME",
    "MAX_DAILY_ATTEMPTS",
    "RETRY_AFTER",
    "AutomaticAnalysisOutcome",
    "AutomaticOutcome",
    "PolicyEvaluation",
    "automatic_stay_window",
    "daily_opportunities",
    "enroll_ready_properties",
    "evaluate_enabled_policies",
    "evaluate_policy",
    "run_automatic_analysis",
]
