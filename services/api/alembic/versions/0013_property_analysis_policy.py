"""Gate 26B: Automatic Analysis Policy V1.

Adds ONE new table, `property_analysis_policies` (one row at most per property): whether AGRIA
enabled automatic analysis for the property and which BOOKINGS data source is its primary one.

Additive and opt-in: no row is inserted, so every existing property stays NOT automated (the
absence of a row means "disabled"). Nothing is guessed or backfilled. Tenant integrity is enforced
by composite foreign keys that reuse the existing `properties (workspace_id, id)` and
`data_sources (workspace_id, property_id, id)` unique constraints; the foreign keys are RESTRICT
like every other operational table.

Written by hand; the model tests keep the ORM metadata in sync with it. Migrations 0001-0012 are
untouched (the head before this gate was `0012_input_provenance`).

Revision ID: 0013_property_analysis_policy
Revises: 0012_input_provenance
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_property_analysis_policy"
down_revision: str | None = "0012_input_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "property_analysis_policies",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("booking_data_source_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_analysis_policies")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_property_analysis_policies_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "booking_data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_property_analysis_policies_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("property_id", name=op.f("uq_property_analysis_policies_property_id")),
        sa.CheckConstraint(
            "NOT enabled OR booking_data_source_id IS NOT NULL",
            name=op.f("ck_property_analysis_policies_enabled_requires_source"),
        ),
    )


def downgrade() -> None:
    op.drop_table("property_analysis_policies")
