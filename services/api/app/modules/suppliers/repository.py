"""Tenant-scoped data access for the Supplier Registry (explicit, no generic base class).

Every query carries the workspace_id of the TenantContext. Repositories `flush()` but never
`commit()`: transaction boundaries belong to the services.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.invoices.cost_categories import CostCategory
from app.modules.suppliers.models import (
    IdentifierKind,
    ReviewReason,
    ReviewStatus,
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)


@dataclass(frozen=True, slots=True)
class SupplierRow:
    id: UUID
    legal_name: str
    normalized_name: str
    country: str | None
    default_cost_category: CostCategory | None


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Everything a resolution needs to know about the registry of ONE workspace (3 queries)."""

    suppliers: list[SupplierRow]
    identifiers: list[tuple[UUID, IdentifierKind, str]]  # supplier id, kind, normalised value
    aliases: list[tuple[UUID, str]]  # supplier id, normalised name


@dataclass(frozen=True, slots=True)
class NewSupplier:
    id: UUID
    legal_name: str
    normalized_name: str
    country: str | None


@dataclass(frozen=True, slots=True)
class NewIdentifier:
    supplier_id: UUID
    kind: IdentifierKind
    normalized_value: str


@dataclass(frozen=True, slots=True)
class NewAlias:
    supplier_id: UUID
    normalized_name: str
    data_source_id: UUID | None


@dataclass(frozen=True, slots=True)
class NewReview:
    provisional_supplier_id: UUID
    candidate_supplier_id: UUID
    reason: ReviewReason
    similarity_score: Decimal


class SupplierRepository:
    """Suppliers, identifiers, aliases and resolution reviews of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    # --- reads --------------------------------------------------------------------------------

    def get(self, supplier_id: UUID) -> Supplier | None:
        return self._session.scalar(
            select(Supplier).where(
                Supplier.workspace_id == self._tenant.workspace_id, Supplier.id == supplier_id
            )
        )

    def list_all(self) -> Sequence[Supplier]:
        return self._session.scalars(
            select(Supplier)
            .where(Supplier.workspace_id == self._tenant.workspace_id)
            .order_by(Supplier.normalized_name, Supplier.id)
        ).all()

    def identifiers_of(self, supplier_id: UUID) -> Sequence[SupplierIdentifier]:
        return self._session.scalars(
            select(SupplierIdentifier)
            .where(
                SupplierIdentifier.workspace_id == self._tenant.workspace_id,
                SupplierIdentifier.supplier_id == supplier_id,
            )
            .order_by(SupplierIdentifier.kind, SupplierIdentifier.normalized_value)
        ).all()

    def aliases_of(self, supplier_id: UUID) -> Sequence[SupplierAlias]:
        return self._session.scalars(
            select(SupplierAlias)
            .where(
                SupplierAlias.workspace_id == self._tenant.workspace_id,
                SupplierAlias.supplier_id == supplier_id,
            )
            .order_by(SupplierAlias.normalized_name)
        ).all()

    def list_reviews(
        self, *, status: ReviewStatus | None = None
    ) -> Sequence[SupplierResolutionReview]:
        query = select(SupplierResolutionReview).where(
            SupplierResolutionReview.workspace_id == self._tenant.workspace_id
        )
        if status is not None:
            query = query.where(SupplierResolutionReview.status == status)
        return self._session.scalars(
            query.order_by(
                SupplierResolutionReview.created_at,
                SupplierResolutionReview.provisional_supplier_id,
                SupplierResolutionReview.candidate_supplier_id,
            )
        ).all()

    def load_registry(self) -> RegistrySnapshot:
        """The whole registry of the workspace in three statements (served by the workspace
        prefix of the supplier indexes). Resolution then works in memory."""
        workspace = self._tenant.workspace_id
        suppliers = [
            SupplierRow(*row)
            for row in self._session.execute(
                select(
                    Supplier.id,
                    Supplier.legal_name,
                    Supplier.normalized_name,
                    Supplier.country,
                    Supplier.default_cost_category,
                )
                .where(Supplier.workspace_id == workspace)
                .order_by(Supplier.normalized_name, Supplier.id)
            )
        ]
        identifiers = [
            (row[0], row[1], row[2])
            for row in self._session.execute(
                select(
                    SupplierIdentifier.supplier_id,
                    SupplierIdentifier.kind,
                    SupplierIdentifier.normalized_value,
                ).where(SupplierIdentifier.workspace_id == workspace)
            )
        ]
        aliases = [
            (row[0], row[1])
            for row in self._session.execute(
                select(SupplierAlias.supplier_id, SupplierAlias.normalized_name).where(
                    SupplierAlias.workspace_id == workspace
                )
            )
        ]
        return RegistrySnapshot(suppliers, identifiers, aliases)

    # --- writes (bulk, one statement per kind) --------------------------------------------------

    def insert_suppliers(self, items: Sequence[NewSupplier]) -> None:
        if not items:
            return
        self._session.execute(
            insert(Supplier),
            [
                {
                    "id": item.id,
                    "workspace_id": self._tenant.workspace_id,
                    "legal_name": item.legal_name,
                    "normalized_name": item.normalized_name,
                    "country": item.country,
                }
                for item in items
            ],
        )

    def insert_identifiers(self, items: Sequence[NewIdentifier]) -> None:
        if not items:
            return
        self._session.execute(
            insert(SupplierIdentifier),
            [
                {
                    "workspace_id": self._tenant.workspace_id,
                    "supplier_id": item.supplier_id,
                    "kind": item.kind,
                    "normalized_value": item.normalized_value,
                }
                for item in items
            ],
        )

    def insert_aliases(self, items: Sequence[NewAlias]) -> None:
        if not items:
            return
        self._session.execute(
            insert(SupplierAlias),
            [
                {
                    "workspace_id": self._tenant.workspace_id,
                    "supplier_id": item.supplier_id,
                    "normalized_name": item.normalized_name,
                    "data_source_id": item.data_source_id,
                }
                for item in items
            ],
        )

    def insert_reviews(self, items: Sequence[NewReview]) -> None:
        if not items:
            return
        self._session.execute(
            insert(SupplierResolutionReview),
            [
                {
                    "workspace_id": self._tenant.workspace_id,
                    "provisional_supplier_id": item.provisional_supplier_id,
                    "candidate_supplier_id": item.candidate_supplier_id,
                    "reason": item.reason,
                    "similarity_score": item.similarity_score,
                    "status": ReviewStatus.PENDING,
                }
                for item in items
            ],
        )

    def set_default_cost_category(
        self, supplier_id: UUID, category: CostCategory | None
    ) -> Supplier:
        """A supplier evolves: its default category is a preference a person may set."""
        supplier = self.get(supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier")
        supplier.default_cost_category = category
        self._session.flush()
        return supplier

    def verify(self, supplier_id: UUID, *, verified: bool = True) -> Supplier:
        supplier = self.get(supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier")
        supplier.is_verified = verified
        self._session.flush()
        return supplier
