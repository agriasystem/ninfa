"""Automatic Analysis Policy V1 (Gate 26B): the FROZEN rules, evaluated for one policy.

Fixed V1 policy (code, not per-property configuration):

* opt-in per property, one explicit primary BOOKINGS source (`PropertyAnalysisPolicy`);
* the stay window is exactly 30 calendar dates starting on the property-local today:
  `end = start + 29 days`, both inclusive (it is also the window REV_OTA_DEPENDENCY needs);
* Revenue + Distribution only: Costs and Labor are never requested (`SKIPPED / NOT_REQUESTED`);
* the automatic opportunity is 10:00 property-local, invoked by an EXTERNAL scheduler
  (`python -m worker dispatch-analysis`); there is no internal periodic job, and the operator
  import cut-off (09:45) is a runbook rule that is NOT stored or checked as a threshold here;
* it runs only if today's booking import exists: the exact source has a SUCCEEDED import with
  `local midnight <= finished_at <= now`. An import finished before local midnight does not count.
  Otherwise it SKIPS - never a stale automatic run (OBSERVED snapshots are immutable per day, so a
  run on yesterday's bookings could not be corrected the same day);
* at most one run per property-local day: a DecisionRun for today (manual or automatic - a run
  does not record its origin) means SKIP;
* no retry; configuration changes apply to future opportunities only and never trigger a run.

Two entry points share one evaluation: the dispatcher/status read it (`evaluate_policy`), and the
policy task (`run_automatic_analysis`) re-evaluates it at execution time and then calls the Gate 25
shared orchestration. This module contains no detector logic and no Procrastinate import.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.analysis.models import PropertyAnalysisPolicy
from app.modules.analysis.policy import (
    AutomaticSkipReason,
    check_configuration,
    list_enabled_policies,
)
from app.modules.analysis.service import (
    AnalysisRunRequest,
    AnalysisRunResult,
    run_property_analysis,
)
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.repository import ImportJobRepository
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.localtime import local_date_of, local_day_start
from app.modules.tenancy.repository import WorkspaceRepository

AUTOMATIC_STAY_WINDOW_DAYS = 30


def automatic_stay_window(local_today: date) -> tuple[date, date]:
    """`(start, end)` inclusive: exactly `AUTOMATIC_STAY_WINDOW_DAYS` dates from `local_today`."""
    return local_today, local_today + timedelta(days=AUTOMATIC_STAY_WINDOW_DAYS - 1)


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """One enabled policy, evaluated at `evaluated_at`. `skip_reason` is None when eligible.
    The fact fields are None when the configuration blocked the evaluation before they could be
    known."""

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
        )

    if not policy.enabled:
        return result(AutomaticSkipReason.POLICY_DISABLED)

    check = check_configuration(
        session, policy.workspace_id, policy.property_id, policy.booking_data_source_id
    )
    local_date = None if check.timezone is None else local_date_of(now, check.timezone)
    if check.blocker is not None:
        return result(check.blocker, local_date)
    assert check.timezone is not None and policy.booking_data_source_id is not None

    run_today = _run_exists_for(session, tenant, policy.property_id, local_date)  # type: ignore[arg-type]
    local_midnight = local_day_start(local_date, check.timezone)  # type: ignore[arg-type]
    import_today = ImportJobRepository(session, tenant).has_succeeded_between(
        policy.booking_data_source_id, local_midnight, now
    )
    latest = _latest_analysis_date(session, tenant, policy.property_id)

    reason: AutomaticSkipReason | None = None
    if run_today:
        reason = AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    elif not import_today:
        reason = AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT
    return result(reason, local_date, run_today, import_today, latest)


def evaluate_enabled_policies(session: Session, now: datetime) -> list[PolicyEvaluation]:
    """Every enabled policy of every workspace, evaluated at the SAME instant `now`."""
    return [evaluate_policy(session, policy, now) for policy in list_enabled_policies(session)]


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
    (dates included), then either skip with a typed reason or run the shared orchestration over
    the 30-date window with Revenue + Distribution only. A real failure propagates."""
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
    start, end = automatic_stay_window(evaluation.local_date)
    result = run_property_analysis(
        session,
        AnalysisRunRequest(
            workspace_id=workspace_id,
            property_id=property_id,
            booking_data_source_id=policy.booking_data_source_id,
            stay_date_start=start,
            stay_date_end=end,
            # Costs and Labor are never requested automatically: SKIPPED / NOT_REQUESTED.
        ),
    )
    return AutomaticAnalysisOutcome(
        AutomaticOutcome.RAN, None, evaluation.local_date, start, end, result
    )
