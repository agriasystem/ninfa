"""Shared helpers for the data-source API tests (Struttura > Fonti dati).

Every file here is REAL bytes in the one canonical format the import services accept (headers = the
services' own canonical field names, see `app.modules.ingestion.canonical_csv`): the API hands them
to the real import services, exactly like the pilot CLI does. Nothing builds an already-parsed
record.
"""

import builtins
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.identity.models import User
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportJob
from app.modules.properties.models import Property
from app.modules.tenancy.models import MembershipRole, Workspace
from tests.invoice_support import fattura_xml
from tests.support import BookingFactory

BOOKING_HEADER = "source_record_id,booked_at,check_in,check_out,status,rooms,room_revenue,channel"
LABOR_HEADER = "work_date,labor_category,planned_hours,planned_cost,currency"
LABOR_DAY = "2026-10-23"


@dataclass
class SourcesEnv:
    """A workspace with ONE property that has NO data source, and a member authenticated on it."""

    workspace: Workspace
    property: Property
    user: User

    @builtins.property
    def base(self) -> str:
        return f"/api/v1/properties/{self.property.id}/data-sources"

    @builtins.property
    def tenant(self) -> TenantContext:
        return TenantContext(self.workspace.id)

    def preview_url(self, domain: str) -> str:
        return f"{self.base}/import-preview?domain={domain}"

    def imports_url(
        self, domain: str, filename: str = "file.csv", snapshot: str | None = None
    ) -> str:
        url = f"{self.base}/imports?domain={domain}&filename={filename}"
        return url if snapshot is None else f"{url}&snapshot_local_date={snapshot}"


def sources_env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    workspace = factory.workspace()
    prop = factory.property(workspace)
    user = factory.user()
    factory.membership(workspace, user, MembershipRole.MEMBER)
    authenticated_as(user.id)
    return SourcesEnv(workspace, prop, user)


def booking_bytes(
    *, channels: tuple[str, ...] = ("Booking.com", "Direct"), extra: str = ""
) -> bytes:
    """One CONFIRMED, 1-room booking per channel, with an optional extra (unrecognized) column."""
    stay = date.today() + timedelta(days=14)
    header = BOOKING_HEADER + (f",{extra}" if extra else "")
    lines = [header]
    for index, channel in enumerate(channels, start=1):
        row = (
            f"SRC-{index:04d},{(stay - timedelta(days=21)).isoformat()},{stay.isoformat()},"
            f"{(stay + timedelta(days=1)).isoformat()},confirmed,1,150.00,{channel}"
        )
        lines.append(row + (",x" if extra else ""))
    return ("\n".join(lines) + "\n").encode("utf-8")


def malformed_booking_bytes() -> bytes:
    """A row with a non-positive `rooms` value: real content that must fail row validation."""
    return (
        BOOKING_HEADER + "\nBAD-0001,2026-09-01,2026-10-05,2026-10-07,confirmed,0,150.00,Direct\n"
    ).encode("utf-8")


def labor_bytes() -> bytes:
    work_date = date.today() + timedelta(days=14)
    return (LABOR_HEADER + f"\n{work_date.isoformat()},HOUSEKEEPING,8,120.00,EUR\n").encode("utf-8")


def raw(client: TestClient, url: str, content: bytes) -> Any:
    """POST a file as the raw request body, the way the page sends it."""
    return client.post(url, content=content, headers={"Content-Type": "application/octet-stream"})


def import_ok(client: TestClient, env: SourcesEnv, domain: str) -> dict[str, Any]:
    """Import one valid file of `domain` and assert it succeeded; returns the response body."""
    if domain == "BOOKINGS":
        response = raw(client, env.imports_url(domain, "prenotazioni.csv"), booking_bytes())
    elif domain == "LABOR":
        url = env.imports_url(domain, "personale.csv", snapshot=LABOR_DAY)
        response = raw(client, url, labor_bytes())
    else:
        response = raw(client, env.imports_url(domain, "fattura.xml"), fattura_xml())
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["succeeded"] is True, body
    return body


def card(client: TestClient, env: SourcesEnv, name: str) -> dict[str, Any]:
    response = client.get(env.base)
    assert response.status_code == 200, response.text
    cards: dict[str, dict[str, Any]] = {item["card"]: item for item in response.json()["cards"]}
    return cards[name]


def sources_of(session: Session, env: SourcesEnv, domain: DataSourceDomain) -> list[DataSource]:
    """Every source row of the property for `domain`, switched off ones included."""
    return list(
        session.scalars(
            select(DataSource).where(
                DataSource.workspace_id == env.workspace.id,
                DataSource.property_id == env.property.id,
                DataSource.domain == domain,
            )
        )
    )


def jobs_of(session: Session, env: SourcesEnv) -> list[ImportJob]:
    return list(
        session.scalars(
            select(ImportJob).where(
                ImportJob.workspace_id == env.workspace.id,
                ImportJob.property_id == env.property.id,
            )
        )
    )
