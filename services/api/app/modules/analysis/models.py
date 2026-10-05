"""The durable automatic-analysis policy of ONE property (Gate 26B).

One row at most per property. Absence of a row, and a row with `enabled = false`, both mean the
same thing: NINFA never analyses this property automatically. Only AGRIA turns it on, through the
internal CLI (`python -m app.cli.analysis_policy`).

Deliberately minimal. The stay window (30 dates), the run time (10:00 property-local, invoked by an
external scheduler), the domains (Revenue + Distribution) and the import rule are FIXED V1 policy,
versioned in code (`app/modules/analysis/automatic.py`), never per-property configuration.

Tenant integrity is enforced by the database with composite foreign keys, the same pattern as
`import_jobs` (docs/architecture/adr/0006-tenant-integrity.md):

    (workspace_id, property_id)                          -> properties (workspace_id, id)
    (workspace_id, property_id, booking_data_source_id)  -> data_sources (workspace_id,
                                                              property_id, id)

so the primary source can never belong to another property or workspace. A foreign key cannot say
"domain is BOOKINGS" or "source is active": the enablement service checks both, and the
dispatcher re-checks them on every opportunity (fail closed, never another source).
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PropertyAnalysisPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "property_analysis_policies"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    # Kept when automation is disabled (history of what was configured); required when enabled.
    booking_data_source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_property_analysis_policies_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "booking_data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_property_analysis_policies_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        # One policy per property (a property id is globally unique; the name says what it means).
        UniqueConstraint("property_id", name="uq_property_analysis_policies_property_id"),
        CheckConstraint(
            "NOT enabled OR booking_data_source_id IS NOT NULL",
            name="enabled_requires_source",
        ),
    )
