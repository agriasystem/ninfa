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
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.invoices.models import (
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    InvoiceMappingProfile,
)
from app.modules.labor.models import (
    LaborEntry,
    LaborImportRow,
    LaborMappingProfile,
    LaborSnapshot,
)
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from app.modules.properties.models import Property
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from app.modules.suppliers.models import (
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from app.modules.tenancy.models import MembershipRole, Workspace, WorkspaceMembership

__all__ = [
    "Booking",
    "BookingChannel",
    "BookingExpectedBaseline",
    "BookingExpectedComparable",
    "BookingImportRow",
    "BookingMappingProfile",
    "BookingSnapshot",
    "BookingStatus",
    "ChannelType",
    "DataSource",
    "DataSourceDomain",
    "DataSourceType",
    "ImportFile",
    "ImportJob",
    "ImportJobStatus",
    "ImportRowStatus",
    "Invoice",
    "InvoiceImportRow",
    "InvoiceLine",
    "InvoiceMappingProfile",
    "LaborCategory",
    "LaborClassificationMethod",
    "LaborEntry",
    "LaborImportRow",
    "LaborMappingProfile",
    "LaborSnapshot",
    "MembershipRole",
    "Property",
    "RoomInventoryDaily",
    "SnapshotOrigin",
    "Supplier",
    "SupplierAlias",
    "SupplierIdentifier",
    "SupplierResolutionReview",
    "User",
    "Workspace",
    "WorkspaceMembership",
]
