"""Shared plumbing for the Gate 21B pilot CLI (`pilot.py`, `imports.py`, `analysis.py`).

Every command resolves its own workspace/property explicitly by slug, passed on the command
line - there is no "current tenant" anywhere in this CLI, and no property is ever selected by a
hidden default. Unknown/foreign slugs raise the same `NotFoundError` the rest of the codebase
already uses, so callers get one consistent error shape everywhere.
"""

import sys
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.tenant import TenantContext
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.models import Workspace
from app.modules.tenancy.repository import WorkspaceRepository

T = TypeVar("T")


def resolve_workspace(session: Session, slug: str) -> Workspace:
    workspace = WorkspaceRepository(session).get_by_slug(slug)
    if workspace is None:
        raise NotFoundError(f"Workspace {slug!r}")
    return workspace


def resolve_property(session: Session, tenant: TenantContext, slug: str) -> Property:
    prop = PropertyRepository(session, tenant).get_by_slug(slug)
    if prop is None:
        raise NotFoundError(f"Property {slug!r}")
    return prop


def resolve_tenant_and_property(
    session: Session, workspace_slug: str, property_slug: str
) -> tuple[TenantContext, Property]:
    workspace = resolve_workspace(session, workspace_slug)
    tenant = TenantContext(workspace_id=workspace.id)
    prop = resolve_property(session, tenant, property_slug)
    return tenant, prop


def run_cli(command: Callable[[], int | None]) -> int:
    """Run one CLI command function: print a clear, single-line error and fail non-zero on any
    expected error. `command` may itself return a non-zero exit code (e.g. "the import ran but
    did not succeed") - that is a normal, expected outcome too, distinct from a raised error.
    Never used to hide a real bug - anything not `AppError`/`ValidationError` still propagates as
    an unhandled exception (a real crash must look like one)."""
    try:
        code = command()
    except (AppError, ValidationError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0 if code is None else code
