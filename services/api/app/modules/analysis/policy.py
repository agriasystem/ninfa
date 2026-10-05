"""Automatic-analysis policy: enablement (fail closed) and the one configuration check (Gate 26B).

`check_configuration` is the ONE place that decides whether a property and its configured booking
source are usable for automatic analysis. Enabling a policy runs it and refuses on any problem;
the dispatcher and the policy task run it again on every automatic opportunity and SKIP with the
same typed reason instead - there is never a fallback to another source.

Absence of a row and `enabled = false` both mean "not automated".
"""

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.tenant import TenantContext
from app.modules.analysis.models import PropertyAnalysisPolicy
from app.modules.ingestion.models import DataSource, DataSourceDomain, DataSourceType
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.repository import WorkspaceRepository


class AutomaticSkipReason(StrEnum):
    """Why a property is NOT automatically analysed right now. The first group is a configuration
    problem (also a refusal reason when enabling); the second group is the day's own state."""

    WORKSPACE_INACTIVE = "WORKSPACE_INACTIVE"
    PROPERTY_INACTIVE = "PROPERTY_INACTIVE"
    INVALID_BOOKING_SOURCE = "INVALID_BOOKING_SOURCE"  # missing / other property / not BOOKINGS
    BOOKING_SOURCE_INACTIVE = "BOOKING_SOURCE_INACTIVE"
    INVALID_TIMEZONE = "INVALID_TIMEZONE"

    POLICY_DISABLED = "POLICY_DISABLED"
    ALREADY_ANALYZED_TODAY = "ALREADY_ANALYZED_TODAY"
    NO_TODAY_BOOKING_IMPORT = "NO_TODAY_BOOKING_IMPORT"
    JOB_ALREADY_QUEUED = "JOB_ALREADY_QUEUED"


class AnalysisPolicyError(AppError):
    """Enabling was refused: the typed `reason` says which fail-closed rule did not hold."""

    def __init__(self, reason: AutomaticSkipReason) -> None:
        super().__init__(
            "analysis_policy_refused",
            f"Automatic analysis cannot be enabled: {reason.value}",
            status_code=HTTPStatus.CONFLICT,
            details={"reason": reason.value},
        )
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ConfigurationCheck:
    """`blocker` is None when the configuration is usable; `timezone` is set whenever the
    property's own timezone is valid (even if another blocker applies)."""

    blocker: AutomaticSkipReason | None
    timezone: ZoneInfo | None = None


def check_configuration(
    session: Session, workspace_id: UUID, property_id: UUID, booking_data_source_id: UUID | None
) -> ConfigurationCheck:
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None or not workspace.is_active or workspace.archived_at is not None:
        return ConfigurationCheck(AutomaticSkipReason.WORKSPACE_INACTIVE)

    tenant = TenantContext(workspace_id=workspace_id)
    prop = PropertyRepository(session, tenant).get(property_id)
    if prop is None or not prop.is_active or prop.archived_at is not None:
        return ConfigurationCheck(AutomaticSkipReason.PROPERTY_INACTIVE)

    try:
        timezone = ZoneInfo(prop.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ConfigurationCheck(AutomaticSkipReason.INVALID_TIMEZONE)

    source = (
        None
        if booking_data_source_id is None
        else session.scalar(
            select(DataSource).where(
                DataSource.workspace_id == workspace_id, DataSource.id == booking_data_source_id
            )
        )
    )
    if (
        source is None
        or source.property_id != property_id
        or source.domain != DataSourceDomain.BOOKINGS
        or source.source_type != DataSourceType.FILE_UPLOAD
    ):
        return ConfigurationCheck(AutomaticSkipReason.INVALID_BOOKING_SOURCE, timezone)
    if not source.is_active:
        return ConfigurationCheck(AutomaticSkipReason.BOOKING_SOURCE_INACTIVE, timezone)
    return ConfigurationCheck(None, timezone)


class AnalysisPolicyService:
    """Enable / disable / show the policy of properties of ONE workspace. Owns its transaction."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def _property(self, property_id: UUID) -> Property:
        prop = PropertyRepository(self._session, self._tenant).get(property_id)
        if prop is None:
            raise NotFoundError("Property")
        return prop

    def get(self, property_id: UUID) -> PropertyAnalysisPolicy | None:
        return self._session.scalar(
            select(PropertyAnalysisPolicy).where(
                PropertyAnalysisPolicy.workspace_id == self._tenant.workspace_id,
                PropertyAnalysisPolicy.property_id == property_id,
            )
        )

    def enable(self, property_id: UUID, booking_data_source_id: UUID) -> PropertyAnalysisPolicy:
        """Enable automation with an EXACT primary BOOKINGS source, or refuse. Never selects a
        source, never triggers a run (a change applies to future automatic opportunities only)."""
        self._property(property_id)
        check = check_configuration(
            self._session, self._tenant.workspace_id, property_id, booking_data_source_id
        )
        if check.blocker is not None:
            raise AnalysisPolicyError(check.blocker)
        try:
            policy = self.get(property_id)
            if policy is None:
                policy = PropertyAnalysisPolicy(
                    workspace_id=self._tenant.workspace_id, property_id=property_id
                )
                self._session.add(policy)
            policy.enabled = True
            policy.booking_data_source_id = booking_data_source_id
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return policy

    def disable(self, property_id: UUID) -> PropertyAnalysisPolicy | None:
        """Switch automation off; the configured source is kept as history. None if never
        configured (nothing to disable, nothing created)."""
        self._property(property_id)
        policy = self.get(property_id)
        if policy is None:
            return None
        try:
            policy.enabled = False
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return policy


def list_enabled_policies(session: Session) -> list[PropertyAnalysisPolicy]:
    """Every enabled policy of EVERY workspace, in a deterministic order.

    Deliberately not tenant-scoped: it is platform-level code for the dispatcher and the operator
    status command (like `WorkspaceRepository`), which then act on each policy through its own
    `TenantContext`. Never reachable from an HTTP route.
    """
    return list(
        session.scalars(
            select(PropertyAnalysisPolicy)
            .where(PropertyAnalysisPolicy.enabled.is_(True))
            .order_by(PropertyAnalysisPolicy.workspace_id, PropertyAnalysisPolicy.property_id)
        ).all()
    )
