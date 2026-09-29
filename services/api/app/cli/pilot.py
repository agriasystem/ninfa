"""Pilot tenant provisioning CLI (Gate 21B): the ONLY supported way to set up a new hotel for a
pilot - there is no signup, no admin portal and no seed script (see
docs/architecture/pilot-readiness-v1.md).

    python -m app.cli.pilot create-workspace --name "Hotel Aurora" --slug hotel-aurora
    python -m app.cli.pilot create-property --workspace-slug hotel-aurora --name "Hotel Aurora" \
        --slug hotel-aurora --timezone Europe/Rome --currency EUR
    python -m app.cli.pilot create-user --email operator@example.com --display-name "Operator"
    python -m app.cli.pilot grant-access --workspace-slug hotel-aurora \
        --email operator@example.com --role OWNER
    python -m app.cli.pilot create-data-source --workspace-slug hotel-aurora \
        --property-slug hotel-aurora --domain BOOKINGS --name "Bookings"
    python -m app.cli.pilot set-room-inventory --workspace-slug hotel-aurora \
        --property-slug hotel-aurora --stay-date-start 2026-10-01 --stay-date-end 2026-10-31 \
        --rooms-available 24

Every command reuses the existing canonical models and repositories unchanged: there is no
parallel setup model. `create-user` never sets a password - use `python -m app.cli.auth
set-password` for that, exactly as it already works for every other user in this system.
"""

import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.cli._support import resolve_tenant_and_property, resolve_workspace, run_cli
from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.db.session import get_sessionmaker
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import UserCreate
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.ingestion.schemas import DataSourceCreate
from app.modules.properties.repository import PropertyRepository
from app.modules.properties.schemas import PropertyCreate
from app.modules.snapshots.repository import RoomInventoryRepository
from app.modules.tenancy.models import MembershipRole
from app.modules.tenancy.repository import MembershipRepository, WorkspaceRepository
from app.modules.tenancy.schemas import MembershipCreate, WorkspaceCreate


def run_create_workspace(session: Session, *, name: str, slug: str) -> None:
    workspace = WorkspaceRepository(session).add(WorkspaceCreate(name=name, slug=slug))
    session.commit()
    print(f"Workspace created: slug={workspace.slug} id={workspace.id}")


def run_create_property(
    session: Session,
    *,
    workspace_slug: str,
    name: str,
    slug: str,
    timezone: str,
    currency: str,
) -> None:
    workspace = resolve_workspace(session, workspace_slug)
    tenant = TenantContext(workspace_id=workspace.id)
    prop = PropertyRepository(session, tenant).add(
        PropertyCreate(name=name, slug=slug, timezone=timezone, currency=currency)
    )
    session.commit()
    print(f"Property created: workspace={workspace_slug} slug={prop.slug} id={prop.id}")


def run_create_user(session: Session, *, email: str, display_name: str | None) -> None:
    user = UserRepository(session).add(UserCreate(email=email, display_name=display_name))
    session.commit()
    print(
        f"User created: email={user.email} id={user.id} "
        "(no password set - use `python -m app.cli.auth set-password`)"
    )


def run_grant_access(
    session: Session, *, workspace_slug: str, email: str, role: MembershipRole
) -> None:
    workspace = resolve_workspace(session, workspace_slug)
    tenant = TenantContext(workspace_id=workspace.id)
    user = UserRepository(session).get_by_email(email)
    if user is None:
        raise NotFoundError(f"User {email!r}")
    membership = MembershipRepository(session, tenant).add(
        MembershipCreate(user_id=user.id, role=role)
    )
    session.commit()
    print(
        f"Access granted: workspace={workspace_slug} email={email} "
        f"role={role.value} membership_id={membership.id}"
    )


def run_create_data_source(
    session: Session,
    *,
    workspace_slug: str,
    property_slug: str,
    domain: DataSourceDomain,
    name: str,
) -> None:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    data_source = DataSourceRepository(session, tenant).add(
        DataSourceCreate(property_id=prop.id, name=name, domain=domain)
    )
    session.commit()
    print(
        f"Data source created: workspace={workspace_slug} property={property_slug} "
        f"domain={domain.value} name={name!r} id={data_source.id}"
    )


def run_set_room_inventory(
    session: Session,
    *,
    workspace_slug: str,
    property_slug: str,
    stay_date_start: date,
    stay_date_end: date,
    rooms_available: int,
    rooms_out_of_order: int,
) -> None:
    if stay_date_start > stay_date_end:
        raise SystemExit("--stay-date-start must not be after --stay-date-end")
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    inventory = RoomInventoryRepository(session, tenant)
    days = (stay_date_end - stay_date_start).days + 1
    for offset in range(days):
        stay_date = date.fromordinal(stay_date_start.toordinal() + offset)
        inventory.set_for_date(
            prop.id,
            stay_date,
            rooms_available=rooms_available,
            rooms_out_of_order=rooms_out_of_order,
        )
    session.commit()
    print(
        f"Room inventory set: workspace={workspace_slug} property={property_slug} "
        f"nights={days} rooms_available={rooms_available} rooms_out_of_order={rooms_out_of_order} "
        f"range={stay_date_start.isoformat()}..{stay_date_end.isoformat()}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_workspace = subparsers.add_parser("create-workspace", help="Create a new workspace.")
    create_workspace.add_argument("--name", required=True)
    create_workspace.add_argument("--slug", required=True)

    create_property = subparsers.add_parser(
        "create-property", help="Create a new property inside an existing workspace."
    )
    create_property.add_argument("--workspace-slug", required=True)
    create_property.add_argument("--name", required=True)
    create_property.add_argument("--slug", required=True)
    create_property.add_argument("--timezone", default="Europe/Rome")
    create_property.add_argument("--currency", default="EUR")

    create_user = subparsers.add_parser("create-user", help="Create a new User (no password).")
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--display-name", default=None)

    grant_access = subparsers.add_parser(
        "grant-access", help="Grant an existing User a role in an existing workspace."
    )
    grant_access.add_argument("--workspace-slug", required=True)
    grant_access.add_argument("--email", required=True)
    grant_access.add_argument(
        "--role", required=True, choices=[role.value for role in MembershipRole]
    )

    create_data_source = subparsers.add_parser(
        "create-data-source", help="Create a new data source for an existing property."
    )
    create_data_source.add_argument("--workspace-slug", required=True)
    create_data_source.add_argument("--property-slug", required=True)
    create_data_source.add_argument(
        "--domain", required=True, choices=[domain.value for domain in DataSourceDomain]
    )
    create_data_source.add_argument("--name", required=True)

    set_room_inventory = subparsers.add_parser(
        "set-room-inventory", help="Set room capacity for a range of stay nights."
    )
    set_room_inventory.add_argument("--workspace-slug", required=True)
    set_room_inventory.add_argument("--property-slug", required=True)
    set_room_inventory.add_argument("--stay-date-start", required=True, type=date.fromisoformat)
    set_room_inventory.add_argument("--stay-date-end", required=True, type=date.fromisoformat)
    set_room_inventory.add_argument("--rooms-available", required=True, type=int)
    set_room_inventory.add_argument("--rooms-out-of-order", type=int, default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    with get_sessionmaker()() as session:

        def dispatch() -> None:
            if args.command == "create-workspace":
                run_create_workspace(session, name=args.name, slug=args.slug)
            elif args.command == "create-property":
                run_create_property(
                    session,
                    workspace_slug=args.workspace_slug,
                    name=args.name,
                    slug=args.slug,
                    timezone=args.timezone,
                    currency=args.currency,
                )
            elif args.command == "create-user":
                run_create_user(session, email=args.email, display_name=args.display_name)
            elif args.command == "grant-access":
                run_grant_access(
                    session,
                    workspace_slug=args.workspace_slug,
                    email=args.email,
                    role=MembershipRole(args.role),
                )
            elif args.command == "create-data-source":
                run_create_data_source(
                    session,
                    workspace_slug=args.workspace_slug,
                    property_slug=args.property_slug,
                    domain=DataSourceDomain(args.domain),
                    name=args.name,
                )
            elif args.command == "set-room-inventory":
                run_set_room_inventory(
                    session,
                    workspace_slug=args.workspace_slug,
                    property_slug=args.property_slug,
                    stay_date_start=args.stay_date_start,
                    stay_date_end=args.stay_date_end,
                    rooms_available=args.rooms_available,
                    rooms_out_of_order=args.rooms_out_of_order,
                )

        return run_cli(dispatch)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "main",
    "run_create_data_source",
    "run_create_property",
    "run_create_user",
    "run_create_workspace",
    "run_grant_access",
    "run_set_room_inventory",
]
