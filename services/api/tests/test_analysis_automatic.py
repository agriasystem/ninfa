"""Gate 26B: the FROZEN automatic-analysis rules, evaluated at an injected instant.

Property-local "today" and local midnight come from `Property.timezone` (never the server's), the
window is exactly 30 dates, today's import must have SUCCEEDED for the EXACT configured source with
`local midnight <= finished_at <= now`, and a DecisionRun for today (manual or automatic) means
skip. The policy runner re-evaluates all of it at execution time and calls the Gate 25 shared
orchestration with Revenue + Distribution only.
"""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.analysis import (
    AnalysisPolicyService,
    AutomaticOutcome,
    AutomaticSkipReason,
    PropertyAnalysisPolicy,
    automatic_stay_window,
    evaluate_enabled_policies,
    evaluate_policy,
    run_automatic_analysis,
)
from app.modules.analysis import automatic as automatic_module
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSourceDomain, ImportJobStatus
from app.modules.tenancy.repository import WorkspaceRepository
from tests.analysis_policy_support import decision_run_on, enable, import_at, utc
from tests.support import BookingFactory

# 2026-10-05 10:00 Europe/Rome (CEST, UTC+2) - the automatic opportunity.
NOW = utc(2026, 10, 5, 8, 0)
LOCAL_MIDNIGHT = utc(2026, 10, 4, 22, 0)  # 2026-10-05 00:00 CEST


def _policy(session: Session, tenant: Any) -> PropertyAnalysisPolicy:
    return enable(session, tenant)


def _reason(session: Session, policy: PropertyAnalysisPolicy, now: datetime = NOW) -> Any:
    return evaluate_policy(session, policy, now).skip_reason


# --- the window ---------------------------------------------------------------------------------


def test_01_the_window_is_exactly_30_inclusive_dates_from_the_local_today() -> None:
    start, end = automatic_stay_window(date(2026, 10, 5))

    assert (start, end) == (date(2026, 10, 5), date(2026, 11, 3))
    assert (end - start).days + 1 == 30


# --- the import gate ----------------------------------------------------------------------------


def test_02_an_import_one_minute_after_local_midnight_qualifies(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, LOCAL_MIDNIGHT + timedelta(minutes=1))  # 00:01 local

    evaluation = evaluate_policy(db_session, policy, NOW)

    assert evaluation.eligible and evaluation.local_date == date(2026, 10, 5)
    assert evaluation.qualifying_import_today is True


def test_03_an_import_just_before_the_dispatch_qualifies_and_one_after_it_does_not(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)

    import_at(factory, tenant.data_source, NOW + timedelta(minutes=1))  # after the dispatch
    assert _reason(db_session, policy) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT

    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 59))  # 09:59 local, before 10:00
    assert _reason(db_session, policy) is None


def test_04_an_import_the_previous_local_evening_does_not_qualify(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 4, 21, 59))  # 23:59 local on 4 October

    evaluation = evaluate_policy(db_session, policy, NOW)

    assert evaluation.skip_reason is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT
    assert evaluation.qualifying_import_today is False
    assert evaluation.run_exists_today is False


def test_05_local_midnight_is_inclusive(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, LOCAL_MIDNIGHT)

    assert _reason(db_session, policy) is None


def test_06_a_failed_import_today_does_not_qualify_even_with_an_older_success(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 3, 9, 0))  # an older SUCCEEDED import
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0), ImportJobStatus.FAILED)

    assert _reason(db_session, policy) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT


def test_07_another_sources_fresh_import_does_not_qualify_the_configured_one(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    other_source = factory.data_source(tenant.property)
    policy = _policy(db_session, tenant)
    import_at(factory, other_source, utc(2026, 10, 5, 7, 0))

    assert _reason(db_session, policy) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT

    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    assert _reason(db_session, policy) is None


def test_08_local_midnight_is_dst_safe_when_clocks_go_back(
    db_session: Session, factory: BookingFactory
) -> None:
    """2026-10-25: Rome leaves summer time at 03:00. Midnight is still UTC+2, so local midnight is
    2026-10-24 22:00 UTC even though the dispatch (10:00 local) is already UTC+1."""
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    now = utc(2026, 10, 25, 9, 0)  # 10:00 CET

    import_at(factory, tenant.data_source, utc(2026, 10, 24, 21, 59))  # 23:59 local on the 24th
    assert _reason(db_session, policy, now) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT

    import_at(factory, tenant.data_source, utc(2026, 10, 24, 22, 30))  # 00:30 local on the 25th
    evaluation = evaluate_policy(db_session, policy, now)
    assert evaluation.eligible and evaluation.local_date == date(2026, 10, 25)


def test_09_local_midnight_is_dst_safe_when_clocks_go_forward(
    db_session: Session, factory: BookingFactory
) -> None:
    """2026-03-29: Rome enters summer time at 02:00. Midnight is still UTC+1, so local midnight is
    2026-03-28 23:00 UTC."""
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    now = utc(2026, 3, 29, 8, 0)  # 10:00 CEST

    import_at(factory, tenant.data_source, utc(2026, 3, 28, 22, 59))  # 23:59 local on the 28th
    assert _reason(db_session, policy, now) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT

    import_at(factory, tenant.data_source, utc(2026, 3, 28, 23, 0))  # exactly local midnight
    assert _reason(db_session, policy, now) is None


def test_10_the_local_date_follows_the_property_timezone_not_utc(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant.property.timezone = "America/New_York"
    db_session.flush()
    policy = _policy(db_session, tenant)
    now = utc(2026, 10, 5, 2, 0)  # still 4 October (22:00 EDT) in New York
    import_at(factory, tenant.data_source, utc(2026, 10, 4, 5, 0))  # 01:00 EDT on the 4th

    evaluation = evaluate_policy(db_session, policy, now)

    assert evaluation.local_date == date(2026, 10, 4)
    assert evaluation.eligible


# --- one run per local day ----------------------------------------------------------------------


def test_11_a_run_today_means_skip_even_when_a_valid_import_exists(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    decision_run_on(db_session, tenant, date(2026, 10, 5))  # manual or automatic: same row

    evaluation = evaluate_policy(db_session, policy, NOW)

    assert evaluation.skip_reason is AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    assert evaluation.run_exists_today is True
    assert evaluation.latest_analysis_date == date(2026, 10, 5)


def test_12_a_previous_day_run_alone_does_not_block_today(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    decision_run_on(db_session, tenant, date(2026, 10, 4))

    evaluation = evaluate_policy(db_session, policy, NOW)

    assert evaluation.eligible
    assert evaluation.run_exists_today is False
    assert evaluation.latest_analysis_date == date(2026, 10, 4)


def test_13_no_run_and_no_import_skips_for_the_import_not_the_run(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)

    assert _reason(db_session, policy) is AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT


# --- dispatch-time revalidation (typed skip, never a fallback) ----------------------------------


def test_14_a_source_deactivated_after_enablement_skips_without_falling_back(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    spare = factory.data_source(tenant.property)  # a perfectly good alternative: never chosen
    import_at(factory, spare, utc(2026, 10, 5, 7, 0))
    policy = _policy(db_session, tenant)
    tenant.data_source.is_active = False
    db_session.flush()

    assert _reason(db_session, policy) is AutomaticSkipReason.BOOKING_SOURCE_INACTIVE


def test_15_a_source_that_is_no_longer_a_bookings_source_skips(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    tenant.data_source.domain = DataSourceDomain.COSTS
    db_session.flush()

    assert _reason(db_session, policy) is AutomaticSkipReason.INVALID_BOOKING_SOURCE


def test_16_a_property_workspace_or_timezone_that_went_bad_skips(
    db_session: Session, factory: BookingFactory
) -> None:
    inactive_property, archived_workspace, bad_timezone = (
        factory.tenant(),
        factory.tenant(),
        factory.tenant(),
    )
    policies = {
        AutomaticSkipReason.PROPERTY_INACTIVE: (
            inactive_property,
            enable(db_session, inactive_property),
        ),
        AutomaticSkipReason.WORKSPACE_INACTIVE: (
            archived_workspace,
            enable(db_session, archived_workspace),
        ),
        AutomaticSkipReason.INVALID_TIMEZONE: (bad_timezone, enable(db_session, bad_timezone)),
    }
    inactive_property.property.is_active = False
    WorkspaceRepository(db_session).archive(archived_workspace.workspace.id)
    bad_timezone.property.timezone = "Not/AZone"
    db_session.flush()

    for expected, (_, policy) in policies.items():
        assert _reason(db_session, policy) is expected


def test_17_a_policy_that_was_disabled_is_not_eligible(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    AnalysisPolicyService(db_session, tenant.context).disable(tenant.property.id)

    assert _reason(db_session, policy) is AutomaticSkipReason.POLICY_DISABLED
    assert evaluate_enabled_policies(db_session, NOW) == []


# --- configuration changes apply to future opportunities only -----------------------------------


def test_18_changing_the_source_after_todays_run_does_not_make_today_runnable_again(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    decision_run_on(db_session, tenant, date(2026, 10, 5))
    new_source = factory.data_source(tenant.property)
    import_at(factory, new_source, utc(2026, 10, 5, 7, 30))

    AnalysisPolicyService(db_session, tenant.context).enable(tenant.property.id, new_source.id)

    db_session.refresh(policy)
    assert _reason(db_session, policy) is AutomaticSkipReason.ALREADY_ANALYZED_TODAY
    assert len(db_session.query(DecisionRun).all()) == 1  # enabling/changing ran nothing


def test_19_re_enabling_executes_nothing_by_itself_and_next_opportunity_decides(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    AnalysisPolicyService(db_session, tenant.context).disable(tenant.property.id)
    assert evaluate_enabled_policies(db_session, NOW) == []

    AnalysisPolicyService(db_session, tenant.context).enable(
        tenant.property.id, tenant.data_source.id
    )

    assert db_session.query(DecisionRun).count() == 0
    [evaluation] = evaluate_enabled_policies(db_session, NOW)
    assert evaluation.policy_id == policy.id and evaluation.eligible


def test_20_the_evaluation_requires_a_timezone_aware_instant(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    policy = _policy(db_session, tenant)

    with pytest.raises(ValueError):
        evaluate_policy(db_session, policy, datetime(2026, 10, 5, 8, 0))


# --- the policy runner --------------------------------------------------------------------------


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, session: Session, request: Any) -> Any:
        self.requests.append(request)
        return object()


def test_21_the_runner_computes_the_window_at_execution_and_requests_only_revenue_and_distribution(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = factory.tenant()
    _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    capture = _Capture()
    monkeypatch.setattr(automatic_module, "run_property_analysis", capture)

    outcome = run_automatic_analysis(db_session, tenant.workspace.id, tenant.property.id, NOW)

    assert outcome.outcome is AutomaticOutcome.RAN and outcome.skip_reason is None
    [request] = capture.requests
    assert request.workspace_id == tenant.workspace.id
    assert request.property_id == tenant.property.id
    assert request.booking_data_source_id == tenant.data_source.id  # the configured source
    assert (request.stay_date_start, request.stay_date_end) == (
        date(2026, 10, 5),
        date(2026, 11, 3),
    )
    # Costs and Labor are never requested: SKIPPED / NOT_REQUESTED in coverage.
    assert request.cost_year is None and request.cost_month is None
    assert request.labor_data_source_id is None and request.currency is None
    assert (outcome.stay_date_start, outcome.stay_date_end) == (
        date(2026, 10, 5),
        date(2026, 11, 3),
    )


def test_22_the_same_job_run_on_the_next_local_day_gets_the_next_days_window(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = factory.tenant()
    _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 6, 7, 0))
    capture = _Capture()
    monkeypatch.setattr(automatic_module, "run_property_analysis", capture)

    run_automatic_analysis(
        db_session, tenant.workspace.id, tenant.property.id, utc(2026, 10, 6, 8, 0)
    )

    assert (capture.requests[0].stay_date_start, capture.requests[0].stay_date_end) == (
        date(2026, 10, 6),
        date(2026, 11, 4),
    )


@pytest.mark.parametrize(
    "setup, reason",
    [
        ("no_import", AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT),
        ("already", AutomaticSkipReason.ALREADY_ANALYZED_TODAY),
        ("source_inactive", AutomaticSkipReason.BOOKING_SOURCE_INACTIVE),
    ],
)
def test_23_the_runner_skips_with_a_typed_reason_and_never_calls_the_analysis(
    db_session: Session,
    factory: BookingFactory,
    monkeypatch: pytest.MonkeyPatch,
    setup: str,
    reason: AutomaticSkipReason,
) -> None:
    tenant = factory.tenant()
    _policy(db_session, tenant)
    if setup != "no_import":
        import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))
    if setup == "already":
        decision_run_on(db_session, tenant, date(2026, 10, 5))
    if setup == "source_inactive":
        tenant.data_source.is_active = False
        db_session.flush()
    capture = _Capture()
    monkeypatch.setattr(automatic_module, "run_property_analysis", capture)

    outcome = run_automatic_analysis(db_session, tenant.workspace.id, tenant.property.id, NOW)

    assert outcome.outcome is AutomaticOutcome.SKIPPED and outcome.skip_reason is reason
    assert capture.requests == []


def test_24_the_runner_skips_a_property_without_a_policy(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = factory.tenant()
    capture = _Capture()
    monkeypatch.setattr(automatic_module, "run_property_analysis", capture)

    outcome = run_automatic_analysis(db_session, tenant.workspace.id, tenant.property.id, NOW)

    assert outcome.skip_reason is AutomaticSkipReason.POLICY_DISABLED
    assert capture.requests == []


def test_25_a_real_failure_of_the_analysis_propagates_through_the_runner(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = factory.tenant()
    _policy(db_session, tenant)
    import_at(factory, tenant.data_source, utc(2026, 10, 5, 7, 0))

    def boom(session: Session, request: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(automatic_module, "run_property_analysis", boom)

    with pytest.raises(RuntimeError, match="engine exploded"):
        run_automatic_analysis(db_session, tenant.workspace.id, tenant.property.id, NOW)


def test_26_the_automatic_module_has_no_detector_logic_and_no_scheduler() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(automatic_module))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not [m for m in imported if m.startswith("app.modules.intelligence")]
    assert not [m for m in imported if m.split(".")[0] in {"procrastinate", "worker", "argparse"}]
