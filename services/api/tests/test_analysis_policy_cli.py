"""Gate 26B: the internal AGRIA CLI `python -m app.cli.analysis_policy` (enable/disable/show)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli._support import run_cli
from app.cli.analysis_policy import run_disable, run_enable, run_show
from app.modules.analysis import PropertyAnalysisPolicy
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSource, DataSourceDomain
from tests.support import BookingFactory


def _hotel(factory: BookingFactory, slug: str) -> tuple[str, str, DataSource]:
    workspace = factory.workspace(f"ws-{slug}")
    prop = factory.property(workspace, f"prop-{slug}")
    return workspace.slug, prop.slug, factory.data_source(prop)


def test_01_enable_reports_the_property_the_source_and_enabled_true(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, source = _hotel(factory, "one")

    code = run_enable(
        db_session, workspace_slug=ws, property_slug=prop, booking_data_source_id=source.id
    )

    assert code == 0
    out = capsys.readouterr().out
    assert f"workspace={ws} property={prop} booking_data_source_id={source.id}" in out
    assert "enabled=true" in out and "no run was triggered" in out
    assert db_session.scalar(select(func.count()).select_from(DecisionRun)) == 0


def test_02_enable_fails_closed_with_a_typed_reason_and_exit_1(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, _ = _hotel(factory, "two")
    labor = factory.data_source(
        factory.property(factory.workspace("ws-other")), DataSourceDomain.LABOR
    )

    code = run_cli(
        lambda: run_enable(
            db_session, workspace_slug=ws, property_slug=prop, booking_data_source_id=labor.id
        )
    )

    assert code == 1
    assert "INVALID_BOOKING_SOURCE" in capsys.readouterr().err
    assert db_session.scalar(select(func.count()).select_from(PropertyAnalysisPolicy)) == 0


def test_03_unknown_slugs_are_a_not_found_error(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, _, source = _hotel(factory, "three")

    code = run_cli(
        lambda: run_enable(
            db_session,
            workspace_slug=ws,
            property_slug="nope-nope",
            booking_data_source_id=source.id,
        )
    )

    assert code == 1 and "not found" in capsys.readouterr().err


def test_04_disable_reports_enabled_false_and_keeps_the_source(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, source = _hotel(factory, "four")
    run_enable(db_session, workspace_slug=ws, property_slug=prop, booking_data_source_id=source.id)
    capsys.readouterr()

    assert run_disable(db_session, workspace_slug=ws, property_slug=prop) == 0

    assert (
        f"property={prop} enabled=false (configuration kept as history)" in capsys.readouterr().out
    )
    policy = db_session.scalars(select(PropertyAnalysisPolicy)).one()
    assert policy.enabled is False and policy.booking_data_source_id == source.id


def test_05_disable_without_a_policy_creates_nothing(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, _ = _hotel(factory, "five")

    assert run_disable(db_session, workspace_slug=ws, property_slug=prop) == 0

    assert "enabled=false (no policy was configured)" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(PropertyAnalysisPolicy)) == 0


def test_06_show_without_a_policy_says_disabled(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, _ = _hotel(factory, "six")

    assert run_show(db_session, workspace_slug=ws, property_slug=prop) == 0

    assert "enabled=false (no policy configured)" in capsys.readouterr().out


def test_07_show_reports_the_source_and_whether_the_configuration_is_still_valid(
    db_session: Session, factory: BookingFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    ws, prop, source = _hotel(factory, "seven")
    run_enable(db_session, workspace_slug=ws, property_slug=prop, booking_data_source_id=source.id)
    capsys.readouterr()

    run_show(db_session, workspace_slug=ws, property_slug=prop)
    valid = capsys.readouterr().out
    assert "enabled=true" in valid and f"booking_data_source_id={source.id}" in valid
    assert "source_domain=BOOKINGS source_active=true configuration=VALID" in valid

    source.is_active = False
    db_session.flush()
    run_show(db_session, workspace_slug=ws, property_slug=prop)
    blocked = capsys.readouterr().out
    assert "source_active=false configuration=BOOKING_SOURCE_INACTIVE" in blocked
