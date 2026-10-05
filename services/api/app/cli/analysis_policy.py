"""AGRIA internal CLI for the automatic-analysis policy (Gate 26B). No customer UI, no API.

    python -m app.cli.analysis_policy enable  --workspace-slug h --property-slug h \
        --booking-data-source-id <uuid>
    python -m app.cli.analysis_policy disable --workspace-slug h --property-slug h
    python -m app.cli.analysis_policy show    --workspace-slug h --property-slug h

Automation is opt-in per property and uses ONE explicit primary BOOKINGS data source - this CLI
never picks a source. `enable` fails closed (typed reason, exit 1) unless the workspace and the
property are active, the source belongs to exactly this workspace/property, is BOOKINGS and active,
and the property's time zone is valid. Enabling or disabling NEVER triggers a run: a change applies
to future automatic opportunities only. The rules themselves (30 dates, 10:00 local, today's import,
Revenue + Distribution only, no retry) are fixed V1 policy: docs/architecture/automatic-analysis-
policy-v1.md.
"""

import argparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.cli._support import resolve_tenant_and_property, run_cli
from app.db.session import get_sessionmaker
from app.modules.analysis import AnalysisPolicyService, check_configuration
from app.modules.ingestion.repository import DataSourceRepository


def run_enable(
    session: Session, *, workspace_slug: str, property_slug: str, booking_data_source_id: UUID
) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    policy = AnalysisPolicyService(session, tenant).enable(prop.id, booking_data_source_id)
    print(
        f"Automatic analysis enabled: workspace={workspace_slug} property={property_slug} "
        f"booking_data_source_id={policy.booking_data_source_id} enabled=true "
        "(applies to future automatic opportunities; no run was triggered)"
    )
    return 0


def run_disable(session: Session, *, workspace_slug: str, property_slug: str) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    policy = AnalysisPolicyService(session, tenant).disable(prop.id)
    detail = "no policy was configured" if policy is None else "configuration kept as history"
    print(
        f"Automatic analysis disabled: workspace={workspace_slug} property={property_slug} "
        f"enabled=false ({detail})"
    )
    return 0


def run_show(session: Session, *, workspace_slug: str, property_slug: str) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    policy = AnalysisPolicyService(session, tenant).get(prop.id)
    if policy is None:
        print(
            f"Automatic analysis policy: workspace={workspace_slug} property={property_slug} "
            "enabled=false (no policy configured)"
        )
        return 0
    line = (
        f"Automatic analysis policy: workspace={workspace_slug} property={property_slug} "
        f"enabled={str(policy.enabled).lower()} "
        f"booking_data_source_id={policy.booking_data_source_id}"
    )
    source = (
        None
        if policy.booking_data_source_id is None
        else DataSourceRepository(session, tenant).get(policy.booking_data_source_id)
    )
    if source is not None:
        line += (
            f" source_domain={source.domain.value} source_active={str(source.is_active).lower()}"
        )
    check = check_configuration(
        session, tenant.workspace_id, prop.id, policy.booking_data_source_id
    )
    line += f" configuration={'VALID' if check.blocker is None else check.blocker.value}"
    print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.analysis_policy")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("enable", "Enable automatic analysis with ONE explicit primary BOOKINGS source."),
        ("disable", "Disable automatic analysis (the configured source is kept as history)."),
        ("show", "Show the policy and whether its configuration is currently valid."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--workspace-slug", required=True)
        command.add_argument("--property-slug", required=True)
        if name == "enable":
            command.add_argument("--booking-data-source-id", required=True, type=UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    with get_sessionmaker()() as session:

        def dispatch() -> int:
            if args.command == "enable":
                return run_enable(
                    session,
                    workspace_slug=args.workspace_slug,
                    property_slug=args.property_slug,
                    booking_data_source_id=args.booking_data_source_id,
                )
            if args.command == "disable":
                return run_disable(
                    session, workspace_slug=args.workspace_slug, property_slug=args.property_slug
                )
            return run_show(
                session, workspace_slug=args.workspace_slug, property_slug=args.property_slug
            )

        return run_cli(dispatch)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_disable", "run_enable", "run_show"]
