"""The Supplier Registry: who NINFA buys from, once per workspace.

A Supplier is owned by the WORKSPACE, not by a property: the same supplier serves several
properties of the same customer (an invoice, in contrast, belongs to one property). It holds an
accounting identity only (legal name, country, default cost category): no address, phone, e-mail,
contact person or bank account. Fiscal identifiers live in `supplier_identifiers`; the bank
account is kept only as the SHA-256 of its normalised form.

Suppliers are NOT immutable: identifiers, aliases, verification and the default category evolve.
Nothing here merges two suppliers (a later gate will, after a person confirms a review).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.invoices.cost_categories import CostCategory


class IdentifierKind(StrEnum):
    VAT_NUMBER = "VAT_NUMBER"
    TAX_CODE = "TAX_CODE"
    IBAN_SHA256 = "IBAN_SHA256"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"
    NOT_DUPLICATE = "NOT_DUPLICATE"


class ReviewReason(StrEnum):
    # A new supplier whose name is close to an existing one: a possible duplicate, never a merge.
    FUZZY_NAME_SIMILARITY = "FUZZY_NAME_SIMILARITY"
    # The same name as an existing supplier, but a different fiscal identity: NOT merged by name.
    NAME_MATCH_IDENTITY_CONFLICT = "NAME_MATCH_IDENTITY_CONFLICT"


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    default_cost_category: Mapped[CostCategory | None] = mapped_column(
        enum_column(CostCategory, 32)
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    is_verified: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_suppliers_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        # Target of every composite foreign key that pins a child row to its supplier's workspace.
        UniqueConstraint("workspace_id", "id", name="uq_suppliers_workspace_id_id"),
        # Exact-name resolution and the candidate scan of the fuzzy review.
        Index("ix_suppliers_workspace_id_normalized_name", "workspace_id", "normalized_name"),
        CheckConstraint("btrim(legal_name) <> ''", name="legal_name_not_blank"),
        CheckConstraint("btrim(normalized_name) <> ''", name="normalized_name_not_blank"),
        CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="country_format"),
        CheckConstraint(
            "default_cost_category IS NULL OR "
            + values_check("default_cost_category", CostCategory),
            name="default_cost_category_valid",
        ),
    )


class SupplierIdentifier(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A stable identifier of a supplier. `normalized_value` is the normalised VAT number or tax
    code, or (IBAN_SHA256) the SHA-256 hex of the normalised IBAN: the raw IBAN is never stored.
    """

    __tablename__ = "supplier_identifiers"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[IdentifierKind] = mapped_column(enum_column(IdentifierKind, 16), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_supplier_identifiers_workspace_id_suppliers",
            ondelete="RESTRICT",
        ),
        # One identifier belongs to ONE supplier of a workspace (the same VAT number may exist in
        # another workspace).
        UniqueConstraint(
            "workspace_id",
            "kind",
            "normalized_value",
            name="uq_supplier_identifiers_workspace_id_kind_normalized_value",
        ),
        # The identifiers of a supplier (also serves the foreign key's RESTRICT check).
        Index("ix_supplier_identifiers_workspace_id_supplier_id", "workspace_id", "supplier_id"),
        CheckConstraint(values_check("kind", IdentifierKind), name="kind_valid"),
        CheckConstraint("btrim(normalized_value) <> ''", name="normalized_value_not_blank"),
        CheckConstraint(
            "kind <> 'IBAN_SHA256' OR normalized_value ~ '^[0-9a-f]{64}$'",
            name="iban_value_is_sha256",
        ),
    )


class SupplierAlias(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A normalised spelling under which a supplier appeared. NOT unique across suppliers: two
    suppliers may really have alike names, and an ambiguous alias is never used to choose one.
    """

    __tablename__ = "supplier_aliases"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Where the spelling was first seen (informational; a workspace-wide alias when NULL).
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_supplier_aliases_workspace_id_suppliers",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.id"],
            name="fk_supplier_aliases_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "supplier_id",
            "normalized_name",
            name="uq_supplier_aliases_workspace_id_supplier_id_normalized_name",
        ),
        Index(
            "ix_supplier_aliases_workspace_id_normalized_name", "workspace_id", "normalized_name"
        ),
        CheckConstraint("btrim(normalized_name) <> ''", name="normalized_name_not_blank"),
    )


class SupplierResolutionReview(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A possible duplicate for a person to confirm later. Gate 6 only creates PENDING reviews:
    there is no merge and no review endpoint yet.
    """

    __tablename__ = "supplier_resolution_reviews"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provisional_supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    candidate_supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reason: Mapped[ReviewReason] = mapped_column(enum_column(ReviewReason, 32), nullable=False)
    similarity_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus, 20),
        nullable=False,
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "provisional_supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_supplier_reviews_workspace_id_provisional_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "candidate_supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_supplier_reviews_workspace_id_candidate_supplier",
            ondelete="RESTRICT",
        ),
        # One review per pair: a rerun never opens the same question twice.
        UniqueConstraint(
            "workspace_id",
            "provisional_supplier_id",
            "candidate_supplier_id",
            name="uq_supplier_reviews_workspace_id_provisional_candidate",
        ),
        Index("ix_supplier_reviews_workspace_id_status", "workspace_id", "status"),
        CheckConstraint(
            "provisional_supplier_id <> candidate_supplier_id", name="provisional_is_not_candidate"
        ),
        CheckConstraint(values_check("reason", ReviewReason), name="reason_valid"),
        CheckConstraint(values_check("status", ReviewStatus), name="status_valid"),
        CheckConstraint("similarity_score BETWEEN 0 AND 1", name="similarity_score_range"),
        CheckConstraint(
            "(status = 'PENDING') = (resolved_at IS NULL)", name="resolved_matches_status"
        ),
    )
