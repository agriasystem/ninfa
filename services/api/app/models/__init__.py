"""ORM model registry.

Importing this package registers every mapped class on `Base.metadata` (Alembic and the
relationship() string references rely on it). Models live in their module
(`app/modules/<module>/models.py`); a model added by a later gate must be imported here.
"""

from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    BookingStatus,
    ChannelType,
    ImportRowStatus,
)
from app.modules.identity.models import User
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.properties.models import Property
from app.modules.tenancy.models import MembershipRole, Workspace, WorkspaceMembership

__all__ = [
    "Booking",
    "BookingChannel",
    "BookingImportRow",
    "BookingMappingProfile",
    "BookingStatus",
    "ChannelType",
    "DataSource",
    "DataSourceDomain",
    "DataSourceType",
    "ImportFile",
    "ImportJob",
    "ImportJobStatus",
    "ImportRowStatus",
    "MembershipRole",
    "Property",
    "User",
    "Workspace",
    "WorkspaceMembership",
]
