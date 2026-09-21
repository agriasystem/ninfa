"""SupplierResolver: from what an invoice says about its supplier to ONE canonical Supplier.

Separate from any parser and from the import service: it takes canonical evidence (a legal name and
normalised identifiers, the IBAN already hashed) and needs only a Session and a TenantContext. It
works in two steps that a test can also use separately:

    plan(evidences)   reads the registry (three statements), decides IN MEMORY, writes nothing;
                      raises SupplierError when the evidence cannot be resolved safely
    apply(plan)       writes the new suppliers, identifiers, aliases and reviews

Priority (policy `supplier-resolution-v1`, ADR 0012):

  1. VAT number, 2. tax code, 3. IBAN hash          exact identifier
  4. exact normalised legal name / alias            only when it points at ONE compatible supplier
  5. fuzzy name similarity                          NEVER assigns anything: it only opens a
                                                    PENDING possible-duplicate review

Stable identifiers outrank the name. Two identifiers of one record that point at different
suppliers, or that contradict the supplier they matched, are a hard SUPPLIER_IDENTITY_CONFLICT:
NINFA does not guess. A name that fits several suppliers is SUPPLIER_NAME_AMBIGUOUS. With no safe
match a NEW supplier is created (unverified) and, when a plausible existing one exists, a review.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import ResolutionMethod
from app.modules.suppliers.errors import SupplierError, SupplierErrorCode
from app.modules.suppliers.models import IdentifierKind, ReviewReason
from app.modules.suppliers.normalization import (
    FUZZY_REVIEW_MIN_SIMILARITY,
    MAX_REVIEWS_PER_SUPPLIER,
    display_name,
    normalize_country,
    normalize_supplier_name,
    normalize_tax_code,
    normalize_vat_number,
    similarity,
)
from app.modules.suppliers.repository import (
    NewAlias,
    NewIdentifier,
    NewReview,
    NewSupplier,
    RegistrySnapshot,
    SupplierRepository,
    SupplierRow,
)

# Identifier kinds in priority order. VAT and tax code are single-valued (an entity has one of
# each); an IBAN hash is multi-valued (an entity may have several accounts).
_PRIORITY = (IdentifierKind.VAT_NUMBER, IdentifierKind.TAX_CODE, IdentifierKind.IBAN_SHA256)
_SINGLE_VALUED = (IdentifierKind.VAT_NUMBER, IdentifierKind.TAX_CODE)
_METHOD_OF_KIND = {
    IdentifierKind.VAT_NUMBER: ResolutionMethod.VAT_NUMBER,
    IdentifierKind.TAX_CODE: ResolutionMethod.TAX_CODE,
    IdentifierKind.IBAN_SHA256: ResolutionMethod.IBAN_SHA256,
}
_ONE = Decimal("1.0000")


class ResolutionOutcome(StrEnum):
    MATCHED_EXACT_IDENTIFIER = "MATCHED_EXACT_IDENTIFIER"
    MATCHED_EXACT_NAME = "MATCHED_EXACT_NAME"
    CREATED_NEW = "CREATED_NEW"
    CREATED_NEW_WITH_REVIEW = "CREATED_NEW_WITH_REVIEW"


@dataclass(frozen=True, slots=True)
class SupplierEvidence:
    """What one document says about its supplier, canonical and minimal.

    There is no raw IBAN here (only hashes), no address, no e-mail, no phone.
    """

    legal_name: str
    normalized_name: str
    country: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    iban_sha256: tuple[str, ...] = ()
    data_source_id: UUID | None = None

    @classmethod
    def build(
        cls,
        *,
        legal_name: str,
        country: str | None = None,
        vat_number: str | None = None,
        tax_code: str | None = None,
        iban_sha256: Sequence[str] = (),
        data_source_id: UUID | None = None,
    ) -> "SupplierEvidence":
        """Normalise the values; a malformed VAT number or tax code raises ValueError."""
        name = display_name(legal_name)
        normalized = normalize_supplier_name(name)
        if not normalized:
            raise ValueError("the legal name has no letters or digits")
        code = normalize_country(country)
        return cls(
            legal_name=name,
            normalized_name=normalized,
            country=code,
            vat_number=None if not vat_number else normalize_vat_number(vat_number, code),
            tax_code=None if not tax_code else normalize_tax_code(tax_code),
            iban_sha256=tuple(sorted(set(iban_sha256))),
            data_source_id=data_source_id,
        )

    def identifiers(self) -> list[tuple[IdentifierKind, str]]:
        found: list[tuple[IdentifierKind, str]] = []
        if self.vat_number:
            found.append((IdentifierKind.VAT_NUMBER, self.vat_number))
        if self.tax_code:
            found.append((IdentifierKind.TAX_CODE, self.tax_code))
        found.extend((IdentifierKind.IBAN_SHA256, digest) for digest in self.iban_sha256)
        return found

    def value_of(self, kind: IdentifierKind) -> str | None:
        return self.vat_number if kind == IdentifierKind.VAT_NUMBER else self.tax_code

    @property
    def key(self) -> tuple[str, str | None, str | None, tuple[str, ...]]:
        """What distinguishes one piece of evidence from another inside a batch."""
        return (self.normalized_name, self.vat_number, self.tax_code, self.iban_sha256)


@dataclass(frozen=True, slots=True)
class SupplierResolution:
    """The typed outcome, with the evidence for it (kinds and ids, never identifier values)."""

    supplier_id: UUID
    outcome: ResolutionOutcome
    method: ResolutionMethod
    created: bool
    matched_identifier_kinds: tuple[IdentifierKind, ...] = ()
    enriched_identifier_kinds: tuple[IdentifierKind, ...] = ()
    alias_added: bool = False
    review_candidate_ids: tuple[UUID, ...] = ()
    default_cost_category: CostCategory | None = None


@dataclass(slots=True)
class ResolutionPlan:
    """What resolving a batch will write; nothing is written until `apply`."""

    resolutions: dict[tuple[str, str | None, str | None, tuple[str, ...]], SupplierResolution] = (
        field(default_factory=dict)
    )
    suppliers: list[NewSupplier] = field(default_factory=list)
    identifiers: list[NewIdentifier] = field(default_factory=list)
    aliases: list[NewAlias] = field(default_factory=list)
    reviews: list[NewReview] = field(default_factory=list)


class _Registry:
    """The registry of a workspace in memory, updated as the batch is planned (so two documents
    of one file that name the same new supplier meet the same one)."""

    def __init__(self, snapshot: RegistrySnapshot) -> None:
        self.suppliers = {row.id: row for row in snapshot.suppliers}
        self.by_identifier: dict[tuple[IdentifierKind, str], UUID] = {}
        self.kinds_of: dict[UUID, set[IdentifierKind]] = defaultdict(set)
        self.names_of: dict[UUID, set[str]] = defaultdict(set)
        self.by_name: dict[str, set[UUID]] = defaultdict(set)
        self.primary_names: dict[str, set[UUID]] = defaultdict(set)
        for row in snapshot.suppliers:
            self._add_name(row.id, row.normalized_name, primary=True)
        for supplier_id, kind, value in snapshot.identifiers:
            self._add_identifier(supplier_id, kind, value)
        for supplier_id, name in snapshot.aliases:
            self._add_name(supplier_id, name, primary=False)

    def _add_name(self, supplier_id: UUID, name: str, *, primary: bool) -> None:
        self.names_of[supplier_id].add(name)
        self.by_name[name].add(supplier_id)
        if primary:
            self.primary_names[name].add(supplier_id)

    def _add_identifier(self, supplier_id: UUID, kind: IdentifierKind, value: str) -> None:
        self.by_identifier[(kind, value)] = supplier_id
        self.kinds_of[supplier_id].add(kind)

    def add_supplier(self, item: NewSupplier) -> None:
        self.suppliers[item.id] = SupplierRow(
            item.id, item.legal_name, item.normalized_name, item.country, None
        )
        self._add_name(item.id, item.normalized_name, primary=True)

    def add_identifier(self, item: NewIdentifier) -> None:
        self._add_identifier(item.supplier_id, item.kind, item.normalized_value)

    def add_alias(self, supplier_id: UUID, name: str) -> None:
        self._add_name(supplier_id, name, primary=False)

    def contradicts(self, supplier_id: UUID, evidence: SupplierEvidence) -> bool:
        """Does the evidence carry a VAT number / tax code where the supplier already has a
        DIFFERENT one? (A record that matched the supplier by that value would not get here.)"""
        return any(
            evidence.value_of(kind) is not None and kind in self.kinds_of[supplier_id]
            for kind in _SINGLE_VALUED
        )


class SupplierResolver:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the supplier resolver needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._suppliers = SupplierRepository(session, tenant)

    # --- public API ---------------------------------------------------------------------------

    def resolve(self, evidences: Sequence[SupplierEvidence]) -> ResolutionPlan:
        """Plan and apply. Runs inside the caller's transaction (it never commits)."""
        plan = self.plan(evidences)
        self.apply(plan)
        return plan

    def plan(self, evidences: Sequence[SupplierEvidence]) -> ResolutionPlan:
        """Decide for every distinct evidence, in order, without writing anything."""
        registry = _Registry(self._suppliers.load_registry())
        plan = ResolutionPlan()
        for evidence in evidences:
            if evidence.key in plan.resolutions:
                continue
            plan.resolutions[evidence.key] = self._plan_one(evidence, registry, plan)
        return plan

    def apply(self, plan: ResolutionPlan) -> None:
        self._suppliers.insert_suppliers(plan.suppliers)
        self._suppliers.insert_identifiers(plan.identifiers)
        self._suppliers.insert_aliases(plan.aliases)
        self._suppliers.insert_reviews(plan.reviews)
        self._session.flush()

    # --- one piece of evidence ----------------------------------------------------------------

    def _plan_one(
        self, evidence: SupplierEvidence, registry: _Registry, plan: ResolutionPlan
    ) -> SupplierResolution:
        pairs = evidence.identifiers()
        matches: dict[UUID, list[IdentifierKind]] = defaultdict(list)
        for kind, value in pairs:
            supplier_id = registry.by_identifier.get((kind, value))
            if supplier_id is not None:
                matches[supplier_id].append(kind)

        if len(matches) > 1:
            raise SupplierError(
                SupplierErrorCode.IDENTITY_CONFLICT,
                "The identifiers of one document point at different suppliers",
                details={
                    "reason": "identifiers_point_at_different_suppliers",
                    "supplier_count": len(matches),
                    "kinds": sorted({k.value for kinds in matches.values() for k in kinds}),
                },
            )
        if matches:
            ((supplier_id, kinds),) = matches.items()
            return self._match_by_identifier(evidence, registry, plan, supplier_id, kinds)
        return self._by_name(evidence, registry, plan)

    def _match_by_identifier(
        self,
        evidence: SupplierEvidence,
        registry: _Registry,
        plan: ResolutionPlan,
        supplier_id: UUID,
        kinds: list[IdentifierKind],
    ) -> SupplierResolution:
        # A VAT number / tax code that differs from the one the supplier already has means a
        # different legal entity that merely shares (say) a bank account: never merged.
        for kind in _SINGLE_VALUED:
            value = evidence.value_of(kind)
            if (
                value is not None
                and registry.by_identifier.get((kind, value)) != supplier_id
                and kind in registry.kinds_of[supplier_id]
            ):
                raise SupplierError(
                    SupplierErrorCode.IDENTITY_CONFLICT,
                    "A stable identifier contradicts the supplier that another identifier matched",
                    details={
                        "reason": "identifier_contradicts_matched_supplier",
                        "kind": kind.value,
                    },
                )
        enriched = self._enrich(evidence, registry, plan, supplier_id)
        alias_added = self._add_alias_if_new(evidence, registry, plan, supplier_id)
        method = _METHOD_OF_KIND[min(kinds, key=_PRIORITY.index)]
        return SupplierResolution(
            supplier_id=supplier_id,
            outcome=ResolutionOutcome.MATCHED_EXACT_IDENTIFIER,
            method=method,
            created=False,
            matched_identifier_kinds=tuple(sorted(set(kinds), key=_PRIORITY.index)),
            enriched_identifier_kinds=enriched,
            alias_added=alias_added,
            default_cost_category=registry.suppliers[supplier_id].default_cost_category,
        )

    def _by_name(
        self, evidence: SupplierEvidence, registry: _Registry, plan: ResolutionPlan
    ) -> SupplierResolution:
        candidates = sorted(registry.by_name.get(evidence.normalized_name, set()), key=str)
        if not candidates:
            return self._create(evidence, registry, plan, conflicting=[])
        compatible = [c for c in candidates if not registry.contradicts(c, evidence)]
        if len(compatible) > 1:
            raise SupplierError(
                SupplierErrorCode.NAME_AMBIGUOUS,
                "The name fits more than one supplier and nothing else tells them apart",
                details={"supplier_ids": [str(c) for c in compatible]},
            )
        if not compatible:
            # Same name, different fiscal identity: a NEW supplier, and a person will look.
            return self._create(evidence, registry, plan, conflicting=candidates)
        supplier_id = compatible[0]
        enriched = self._enrich(evidence, registry, plan, supplier_id)
        by_primary = supplier_id in registry.primary_names.get(evidence.normalized_name, set())
        return SupplierResolution(
            supplier_id=supplier_id,
            outcome=ResolutionOutcome.MATCHED_EXACT_NAME,
            method=ResolutionMethod.EXACT_NAME if by_primary else ResolutionMethod.EXACT_ALIAS,
            created=False,
            enriched_identifier_kinds=enriched,
            default_cost_category=registry.suppliers[supplier_id].default_cost_category,
        )

    def _create(
        self,
        evidence: SupplierEvidence,
        registry: _Registry,
        plan: ResolutionPlan,
        *,
        conflicting: list[UUID],
    ) -> SupplierResolution:
        new = NewSupplier(uuid4(), evidence.legal_name, evidence.normalized_name, evidence.country)
        plan.suppliers.append(new)
        registry.add_supplier(new)
        for kind, value in evidence.identifiers():
            item = NewIdentifier(new.id, kind, value)
            plan.identifiers.append(item)
            registry.add_identifier(item)
        plan.aliases.append(NewAlias(new.id, evidence.normalized_name, evidence.data_source_id))
        registry.add_alias(new.id, evidence.normalized_name)

        reviewed: list[UUID] = []
        for candidate in conflicting[:MAX_REVIEWS_PER_SUPPLIER]:
            plan.reviews.append(
                NewReview(new.id, candidate, ReviewReason.NAME_MATCH_IDENTITY_CONFLICT, _ONE)
            )
            reviewed.append(candidate)
        for candidate, score in self._fuzzy_candidates(evidence, registry, new.id, set(reviewed)):
            if len(reviewed) >= MAX_REVIEWS_PER_SUPPLIER:
                break
            plan.reviews.append(
                NewReview(new.id, candidate, ReviewReason.FUZZY_NAME_SIMILARITY, score)
            )
            reviewed.append(candidate)
        return SupplierResolution(
            supplier_id=new.id,
            outcome=(
                ResolutionOutcome.CREATED_NEW_WITH_REVIEW
                if reviewed
                else ResolutionOutcome.CREATED_NEW
            ),
            method=(
                ResolutionMethod.CREATED_NEW_WITH_REVIEW
                if reviewed
                else ResolutionMethod.CREATED_NEW
            ),
            created=True,
            review_candidate_ids=tuple(reviewed),
        )

    # --- helpers ------------------------------------------------------------------------------

    def _fuzzy_candidates(
        self,
        evidence: SupplierEvidence,
        registry: _Registry,
        new_id: UUID,
        skip: set[UUID],
    ) -> list[tuple[UUID, Decimal]]:
        """Plausible duplicates, best first. A supplier with a DIFFERENT VAT number / tax code
        is a different legal entity and is not proposed."""
        scored: list[tuple[UUID, Decimal]] = []
        for supplier_id in registry.suppliers:
            if supplier_id == new_id or supplier_id in skip:
                continue
            if registry.contradicts(supplier_id, evidence):
                continue
            best = max(
                (
                    similarity(evidence.normalized_name, name)
                    for name in registry.names_of[supplier_id]
                ),
                default=Decimal(0),
            )
            if best >= FUZZY_REVIEW_MIN_SIMILARITY:
                scored.append((supplier_id, best))
        scored.sort(
            key=lambda item: (-item[1], registry.suppliers[item[0]].normalized_name, str(item[0]))
        )
        return scored

    def _enrich(
        self,
        evidence: SupplierEvidence,
        registry: _Registry,
        plan: ResolutionPlan,
        supplier_id: UUID,
    ) -> tuple[IdentifierKind, ...]:
        """Add the identifiers the registry does not know yet (and no other supplier owns)."""
        added: list[IdentifierKind] = []
        for kind, value in evidence.identifiers():
            if (kind, value) in registry.by_identifier:
                continue
            item = NewIdentifier(supplier_id, kind, value)
            plan.identifiers.append(item)
            registry.add_identifier(item)
            added.append(kind)
        return tuple(sorted(set(added), key=_PRIORITY.index))

    def _add_alias_if_new(
        self,
        evidence: SupplierEvidence,
        registry: _Registry,
        plan: ResolutionPlan,
        supplier_id: UUID,
    ) -> bool:
        if evidence.normalized_name in registry.names_of[supplier_id]:
            return False
        plan.aliases.append(
            NewAlias(supplier_id, evidence.normalized_name, evidence.data_source_id)
        )
        registry.add_alias(supplier_id, evidence.normalized_name)
        return True
