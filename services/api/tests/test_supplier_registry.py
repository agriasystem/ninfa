"""The Supplier Registry and SupplierResolver on real PostgreSQL (Gate 6 groups A and B).

The resolver is exercised with canonical evidence only (no file, no HTTP, no import service).
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg.errors as pg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import ResolutionMethod
from app.modules.suppliers.errors import SupplierError, SupplierErrorCode
from app.modules.suppliers.models import (
    IdentifierKind,
    ReviewReason,
    ReviewStatus,
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from app.modules.suppliers.normalization import (
    FUZZY_REVIEW_MIN_SIMILARITY,
    MAX_REVIEWS_PER_SUPPLIER,
    RESOLUTION_POLICY_VERSION,
    hash_iban,
    normalize_iban,
    normalize_supplier_name,
    normalize_tax_code,
    normalize_vat_number,
    similarity,
)
from app.modules.suppliers.repository import NewIdentifier, SupplierRepository
from app.modules.suppliers.resolution import (
    ResolutionOutcome,
    SupplierEvidence,
    SupplierResolver,
)
from tests.invoice_support import IBAN_A, IBAN_B, IBAN_C
from tests.support import BookingFactory, Rejects, Tenant

Outcome = ResolutionOutcome
DIGEST_A = hashlib.sha256(IBAN_A.encode()).hexdigest()
DIGEST_B = hashlib.sha256(IBAN_B.encode()).hexdigest()


def evidence(
    name: str = "Fornitore Uno S.r.l.",
    *,
    vat: str | None = None,
    tax: str | None = None,
    ibans: tuple[str, ...] = (),
    country: str | None = "IT",
) -> SupplierEvidence:
    return SupplierEvidence.build(
        legal_name=name,
        country=country,
        vat_number=vat,
        tax_code=tax,
        iban_sha256=[h for h in (hash_iban(i) for i in ibans) if h],
    )


class World:
    """One tenant and its resolver."""

    def __init__(self, session: Session, tenant: Tenant) -> None:
        self.session = session
        self.tenant = tenant
        self.resolver = SupplierResolver(session, tenant.context)
        self.repo = SupplierRepository(session, tenant.context)

    def resolve(self, *evidences: SupplierEvidence) -> list[Any]:
        plan = self.resolver.resolve(evidences)
        return [plan.resolutions[e.key] for e in evidences]

    def one(self, item: SupplierEvidence) -> Any:
        return self.resolve(item)[0]

    def count(self, model: type[Any]) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.workspace_id == self.tenant.workspace.id)
            )
            or 0
        )

    def supplier(self, supplier_id: UUID) -> Supplier:
        found = self.repo.get(supplier_id)
        assert found is not None
        return found

    def kinds(self, supplier_id: UUID) -> set[IdentifierKind]:
        return {i.kind for i in self.repo.identifiers_of(supplier_id)}


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> World:
    return World(db_session, factory.tenant())


# --- A. the supplier model ----------------------------------------------------------------------


def test_a_supplier_belongs_to_the_workspace_and_stores_no_contact_data(world: World) -> None:
    columns = {column.name for column in Supplier.__table__.columns}
    assert columns == {
        "id",
        "workspace_id",
        "legal_name",
        "normalized_name",
        "country",
        "default_cost_category",
        "is_active",
        "is_verified",
        "created_at",
        "updated_at",
    }
    assert "property_id" not in columns  # workspace-wide, not property-owned
    forbidden = ("email", "phone", "telefono", "address", "indirizzo", "pec", "contact", "iban")
    assert not [c for c in columns if any(word in c for word in forbidden)]
    for table in (SupplierIdentifier.__table__, SupplierAlias.__table__):
        assert "property_id" not in {c.name for c in table.columns}


def test_a_new_supplier_is_unverified_active_and_without_a_default_category(world: World) -> None:
    resolution = world.one(evidence("Nuovo Fornitore S.r.l.", vat="01234567890"))

    supplier = world.supplier(resolution.supplier_id)
    assert (supplier.is_verified, supplier.is_active) == (False, True)
    assert supplier.default_cost_category is None
    assert supplier.legal_name == "Nuovo Fornitore S.r.l." and supplier.country == "IT"
    assert supplier.normalized_name == "nuovo fornitore srl"


def test_the_normalized_name_ignores_case_accents_punctuation_and_spacing() -> None:
    forms = ["Caffè  Rossi S.r.l.", "CAFFE ROSSI SRL", "caffe' rossi  s.r.l", "Caffè-Rossi S.R.L."]
    assert len({normalize_supplier_name(form) for form in forms}) == 1


def test_different_legal_forms_are_not_the_same_name() -> None:
    assert normalize_supplier_name("Rossi Food SRL") != normalize_supplier_name("Rossi Food SPA")


def test_vat_numbers_are_normalised_to_country_plus_code() -> None:
    assert normalize_vat_number("it 012.345.678-90") == "IT01234567890"
    assert normalize_vat_number("01234567890") == "IT01234567890"  # bare 11 digits: Italian
    assert normalize_vat_number("123456789", "DE") == "DE123456789"
    assert normalize_vat_number("ESB12345678") == "ESB12345678"  # foreign, no checksum


@pytest.mark.parametrize("bad", ["", "IT123", "1", "!!", "IT0123456789A", "X"])
def test_a_structurally_invalid_vat_number_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_vat_number(bad)


def test_tax_codes_are_upper_cased_without_whitespace() -> None:
    assert normalize_tax_code(" rssmra80a01 h501u ") == "RSSMRA80A01H501U"
    assert normalize_tax_code("01234567890") == "01234567890"  # a company's is numeric
    with pytest.raises(ValueError):
        normalize_tax_code("ab")


def test_the_iban_is_normalised_then_hashed_and_the_raw_value_is_not_returned() -> None:
    assert normalize_iban("it60 x054 2811 1010 0000 0123 456") == IBAN_A
    assert hash_iban(IBAN_A) == DIGEST_A == hash_iban(" it60 X054 2811 1010 0000 0123 456 ")
    assert hash_iban("IT00X0542811101000000123456") is None  # bad check digits
    assert IBAN_A not in (hash_iban(IBAN_A) or "")


def test_an_identifier_is_unique_in_a_workspace_and_may_repeat_in_another(
    world: World, factory: BookingFactory, rejects: Rejects, db_session: Session
) -> None:
    first = world.one(evidence("Uno", vat="01234567890")).supplier_id
    other = world.one(evidence("Due", vat="09876543210")).supplier_id

    with rejects(pg.UniqueViolation, "uq_supplier_identifiers_workspace_id_kind_normalized_value"):
        db_session.add(
            SupplierIdentifier(
                workspace_id=world.tenant.workspace.id,
                supplier_id=other,
                kind=IdentifierKind.VAT_NUMBER,
                normalized_value="IT01234567890",
            )
        )

    stranger = World(db_session, factory.tenant())  # another workspace: the same VAT is fine
    assert stranger.one(evidence("Uno", vat="01234567890")).supplier_id != first


def test_identifier_kinds_and_iban_digests_are_checked_by_the_database(
    world: World, rejects: Rejects, db_session: Session
) -> None:
    supplier_id = world.one(evidence("Uno")).supplier_id
    workspace_id = world.tenant.workspace.id

    with rejects(pg.CheckViolation, "ck_supplier_identifiers_kind_valid"):
        db_session.execute(
            text(
                "INSERT INTO supplier_identifiers"
                " (workspace_id, supplier_id, kind, normalized_value)"
                " VALUES (:workspace, :supplier, 'PASSPORT', 'X')"
            ),
            {"workspace": workspace_id, "supplier": supplier_id},
        )
    with rejects(pg.CheckViolation, "ck_supplier_identifiers_iban_value_is_sha256"):
        db_session.add(
            SupplierIdentifier(
                workspace_id=workspace_id,
                supplier_id=supplier_id,
                kind=IdentifierKind.IBAN_SHA256,
                normalized_value=IBAN_A,  # a raw IBAN cannot be stored as its own hash
            )
        )


def test_an_alias_may_be_shared_by_two_suppliers_of_the_workspace(
    world: World, db_session: Session
) -> None:
    one = world.one(evidence("Uno", vat="01234567890")).supplier_id
    two = world.one(evidence("Due", vat="09876543210")).supplier_id
    for supplier_id in (one, two):  # no global uniqueness on normalized_name
        db_session.add(
            SupplierAlias(
                workspace_id=world.tenant.workspace.id,
                supplier_id=supplier_id,
                normalized_name="nome condiviso",
            )
        )
    db_session.flush()
    assert world.count(SupplierAlias) == 4


def test_a_supplier_evolves_default_category_and_verification_can_change(world: World) -> None:
    supplier_id = world.one(evidence("Uno")).supplier_id

    world.repo.set_default_cost_category(supplier_id, CostCategory.LAUNDRY)
    world.repo.verify(supplier_id)

    supplier = world.supplier(supplier_id)
    assert supplier.default_cost_category == CostCategory.LAUNDRY and supplier.is_verified


# --- B. resolution: priority and exact identifiers ---------------------------------------------


def test_the_same_vat_number_resolves_to_the_same_supplier_whatever_the_name(world: World) -> None:
    first = world.one(evidence("Rossi Food S.r.l.", vat="01234567890"))

    again = world.one(evidence("ROSSI FOOD SOCIETA A RESPONSABILITA LIMITATA", vat="IT01234567890"))

    assert again.supplier_id == first.supplier_id and not again.created
    assert again.outcome == Outcome.MATCHED_EXACT_IDENTIFIER
    assert again.method == ResolutionMethod.VAT_NUMBER
    assert again.matched_identifier_kinds == (IdentifierKind.VAT_NUMBER,)
    assert again.alias_added  # the new spelling is remembered
    assert world.count(Supplier) == 1


def test_the_tax_code_resolves_when_there_is_no_vat_number(world: World) -> None:
    first = world.one(evidence("Mario Rossi", tax="RSSMRA80A01H501U"))

    again = world.one(evidence("Rossi Mario", tax="rssmra80a01h501u"))

    assert again.supplier_id == first.supplier_id
    assert again.method == ResolutionMethod.TAX_CODE


def test_the_iban_hash_resolves_when_there_is_no_vat_or_tax_code(world: World) -> None:
    first = world.one(evidence("Bar Centrale", ibans=(IBAN_A,)))

    again = world.one(evidence("Il Bar Centrale di Mario", ibans=(IBAN_A,)))

    assert again.supplier_id == first.supplier_id
    assert again.method == ResolutionMethod.IBAN_SHA256


def test_vat_outranks_tax_code_and_tax_code_outranks_iban(world: World) -> None:
    supplier = world.one(
        evidence("Uno", vat="01234567890", tax="01234567890", ibans=(IBAN_A,))
    ).supplier_id

    by_all = world.one(evidence("X1", vat="01234567890", tax="01234567890", ibans=(IBAN_A,)))
    by_tax_and_iban = world.one(evidence("X2", tax="01234567890", ibans=(IBAN_A,)))
    by_iban = world.one(evidence("X3", ibans=(IBAN_A,)))

    assert {by_all.supplier_id, by_tax_and_iban.supplier_id, by_iban.supplier_id} == {supplier}
    assert by_all.method == ResolutionMethod.VAT_NUMBER
    assert by_tax_and_iban.method == ResolutionMethod.TAX_CODE
    assert by_iban.method == ResolutionMethod.IBAN_SHA256


def test_several_identifiers_of_one_supplier_are_a_valid_match(world: World) -> None:
    supplier = world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,))).supplier_id

    again = world.one(evidence("Uno", vat="01234567890", tax="01234567890", ibans=(IBAN_A,)))

    assert again.supplier_id == supplier
    assert again.matched_identifier_kinds == (IdentifierKind.VAT_NUMBER, IdentifierKind.IBAN_SHA256)
    assert again.enriched_identifier_kinds == (IdentifierKind.TAX_CODE,)


def add_identifier(world: World, supplier_id: UUID, kind: IdentifierKind, value: str) -> None:
    world.repo.insert_identifiers([NewIdentifier(supplier_id, kind, value)])
    world.session.flush()


def snapshot(world: World) -> tuple[int, int, int, int]:
    return (
        world.count(Supplier),
        world.count(SupplierIdentifier),
        world.count(SupplierAlias),
        world.count(SupplierResolutionReview),
    )


def test_identifiers_pointing_at_different_suppliers_are_a_hard_conflict(world: World) -> None:
    uno = world.one(evidence("Uno", vat="01234567890")).supplier_id
    due = world.one(evidence("Due", vat="09876543210")).supplier_id
    add_identifier(world, due, IdentifierKind.TAX_CODE, "99999999999")
    before = snapshot(world)

    with pytest.raises(SupplierError) as error:
        # the VAT number is Uno's, the tax code is Due's
        world.resolver.resolve([evidence("Uno", vat="01234567890", tax="99999999999")])

    assert (
        error.value.code == SupplierErrorCode.IDENTITY_CONFLICT
        and SupplierErrorCode.IDENTITY_CONFLICT.value == "SUPPLIER_IDENTITY_CONFLICT"
    )
    assert error.value.details is not None
    assert error.value.details["reason"] == "identifiers_point_at_different_suppliers"
    assert error.value.details["supplier_count"] == 2
    assert snapshot(world) == before  # nothing was written
    assert uno != due


def test_a_stable_identifier_that_contradicts_the_matched_supplier_is_a_hard_conflict(
    world: World,
) -> None:
    world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,)))
    before = snapshot(world)

    with pytest.raises(SupplierError) as error:
        # the same bank account, but another VAT number: another legal entity, never merged
        world.resolver.resolve([evidence("Uno", vat="09876543210", ibans=(IBAN_A,))])

    assert error.value.code == "SUPPLIER_IDENTITY_CONFLICT"
    assert error.value.details is not None
    assert error.value.details["reason"] == "identifier_contradicts_matched_supplier"
    assert error.value.details["kind"] == "VAT_NUMBER"
    assert snapshot(world) == before


def test_the_conflict_error_carries_no_identifier_value(world: World) -> None:
    world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,)))
    with pytest.raises(SupplierError) as error:
        world.resolver.plan([evidence("Uno", vat="09876543210", ibans=(IBAN_A,))])
    text = repr(error.value.details) + error.value.message
    for secret in ("01234567890", "09876543210", IBAN_A, DIGEST_A):
        assert secret not in text


def test_an_unknown_identifier_is_added_to_the_matched_supplier(world: World) -> None:
    first = world.one(evidence("Uno", vat="01234567890"))

    again = world.one(evidence("Uno", vat="01234567890", tax="01234567890", ibans=(IBAN_A,)))

    assert again.supplier_id == first.supplier_id
    assert again.enriched_identifier_kinds == (IdentifierKind.TAX_CODE, IdentifierKind.IBAN_SHA256)
    assert world.kinds(first.supplier_id) == set(IdentifierKind)
    assert world.count(Supplier) == 1


def test_a_second_bank_account_is_added_to_the_same_supplier(world: World) -> None:
    first = world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,)))

    again = world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_B,)))

    assert again.supplier_id == first.supplier_id
    digests = {
        i.normalized_value
        for i in world.repo.identifiers_of(first.supplier_id)
        if i.kind == IdentifierKind.IBAN_SHA256
    }
    assert digests == {DIGEST_A, DIGEST_B}  # an entity may have several accounts


# --- B. resolution: names, aliases, fuzzy -------------------------------------------------------


def test_an_exact_normalised_name_resolves_when_no_identifier_disagrees(world: World) -> None:
    first = world.one(evidence("Caffè Rossi S.r.l."))

    again = world.one(evidence("CAFFE ROSSI SRL"))

    assert again.supplier_id == first.supplier_id and not again.created
    assert again.outcome == Outcome.MATCHED_EXACT_NAME
    assert again.method == ResolutionMethod.EXACT_NAME


def test_a_name_match_enriches_a_supplier_that_had_no_identifiers(world: World) -> None:
    first = world.one(evidence("Caffè Rossi S.r.l."))

    again = world.one(evidence("Caffè Rossi S.r.l.", vat="01234567890"))

    assert again.supplier_id == first.supplier_id
    assert again.enriched_identifier_kinds == (IdentifierKind.VAT_NUMBER,)


def test_an_exact_alias_resolves_and_reports_the_alias_method(world: World) -> None:
    first = world.one(evidence("Rossi Food S.r.l.", vat="01234567890"))
    world.one(evidence("Rossi F. Srl", vat="01234567890"))  # a spelling remembered as an alias

    again = world.one(evidence("Rossi F. Srl"))

    assert again.supplier_id == first.supplier_id
    assert again.outcome == Outcome.MATCHED_EXACT_NAME
    assert again.method == ResolutionMethod.EXACT_ALIAS


def share_alias(world: World, name: str, *suppliers: UUID) -> None:
    for supplier_id in suppliers:
        world.session.add(
            SupplierAlias(
                workspace_id=world.tenant.workspace.id,
                supplier_id=supplier_id,
                normalized_name=name,
            )
        )
    world.session.flush()


def test_a_name_that_fits_two_suppliers_is_ambiguous_and_nothing_is_picked(world: World) -> None:
    uno = world.one(evidence("Bar Uno", vat="01234567890")).supplier_id
    due = world.one(evidence("Bar Due", vat="09876543210")).supplier_id
    share_alias(world, "bar", uno, due)
    before = snapshot(world)

    with pytest.raises(SupplierError) as error:
        world.resolver.resolve([evidence("Bar")])

    assert (
        error.value.code == SupplierErrorCode.NAME_AMBIGUOUS
        and SupplierErrorCode.NAME_AMBIGUOUS.value == "SUPPLIER_NAME_AMBIGUOUS"
    )
    assert snapshot(world) == before
    assert error.value.details is not None
    assert set(error.value.details["supplier_ids"]) == {str(uno), str(due)}


def test_an_ambiguous_name_is_resolved_by_an_identifier_when_the_evidence_has_one(
    world: World,
) -> None:
    uno = world.one(evidence("Bar Uno", vat="01234567890")).supplier_id
    due = world.one(evidence("Bar Due", vat="09876543210")).supplier_id
    share_alias(world, "bar", uno, due)

    assert world.one(evidence("Bar", vat="09876543210")).supplier_id == due


def test_the_same_name_with_a_different_vat_is_a_new_supplier_and_a_review(world: World) -> None:
    first = world.one(evidence("Rossi Food S.r.l.", vat="01234567890")).supplier_id

    other = world.one(evidence("Rossi Food S.r.l.", vat="09876543210"))

    assert other.created and other.supplier_id != first  # NOT merged by name
    assert other.outcome == Outcome.CREATED_NEW_WITH_REVIEW
    assert other.method == ResolutionMethod.CREATED_NEW_WITH_REVIEW
    assert other.review_candidate_ids == (first,)
    (review,) = world.repo.list_reviews()
    assert review.provisional_supplier_id == other.supplier_id
    assert review.candidate_supplier_id == first
    assert review.reason == ReviewReason.NAME_MATCH_IDENTITY_CONFLICT
    assert review.status == ReviewStatus.PENDING and review.resolved_at is None
    assert review.similarity_score == Decimal("1.0000")


def test_a_similar_name_creates_a_new_supplier_with_a_review_never_an_assignment(
    world: World,
) -> None:
    first = world.one(evidence("Rossi Food S.r.l.", vat="01234567890")).supplier_id

    similar = world.one(evidence("Rossi Foods S.r.l."))  # no identifier, not the same name

    assert similar.created and similar.supplier_id != first  # the invoice stays on the NEW one
    assert similar.outcome == Outcome.CREATED_NEW_WITH_REVIEW
    assert similar.review_candidate_ids == (first,)
    (review,) = world.repo.list_reviews(status=ReviewStatus.PENDING)
    assert review.reason == ReviewReason.FUZZY_NAME_SIMILARITY
    assert review.similarity_score >= FUZZY_REVIEW_MIN_SIMILARITY
    assert world.supplier(similar.supplier_id).is_verified is False


def test_srl_and_spa_are_never_auto_merged(world: World) -> None:
    srl = world.one(evidence("Rossi Food S.r.l.", vat="01234567890")).supplier_id

    spa = world.one(evidence("Rossi Food S.p.A."))

    assert spa.supplier_id != srl and spa.created
    assert world.count(Supplier) == 2


def test_a_similar_name_of_a_supplier_with_another_vat_is_not_even_proposed(world: World) -> None:
    world.one(evidence("Rossi Food S.r.l.", vat="01234567890"))

    other = world.one(evidence("Rossi Foods S.r.l.", vat="09876543210"))

    assert other.outcome == Outcome.CREATED_NEW  # two fiscal identities: clearly two entities
    assert world.count(SupplierResolutionReview) == 0


def test_a_dissimilar_name_opens_no_review(world: World) -> None:
    world.one(evidence("Rossi Food S.r.l."))

    other = world.one(evidence("Lavanderia Industriale Puglia"))

    assert other.outcome == Outcome.CREATED_NEW
    assert other.method == ResolutionMethod.CREATED_NEW
    assert world.count(SupplierResolutionReview) == 0


def test_a_new_supplier_gets_its_identifiers_and_its_normalised_alias(world: World) -> None:
    resolution = world.one(
        evidence("Nuovo S.r.l.", vat="01234567890", tax="01234567890", ibans=(IBAN_C,))
    )

    assert world.kinds(resolution.supplier_id) == set(IdentifierKind)
    aliases = [a.normalized_name for a in world.repo.aliases_of(resolution.supplier_id)]
    assert aliases == ["nuovo srl"]


def test_reviews_per_new_supplier_are_bounded(world: World) -> None:
    for name in ("Rossi Food Alpha", "Rossi Food Alfa", "Rossi Food Alpa", "Rossi Food Alph"):
        world.one(evidence(name))
    before = world.count(SupplierResolutionReview)

    created = world.one(evidence("Rossi Food Alpha S"))

    added = world.count(SupplierResolutionReview) - before
    assert created.created and len(created.review_candidate_ids) == added
    assert added <= 3  # MAX_REVIEWS_PER_SUPPLIER


def test_the_same_evidence_twice_in_a_batch_meets_one_supplier(world: World) -> None:
    first, second = world.resolve(
        evidence("Batch S.r.l.", vat="01234567890"), evidence("BATCH SRL", vat="01234567890")
    )

    assert first.supplier_id == second.supplier_id
    assert world.count(Supplier) == 1


def test_two_documents_of_one_batch_naming_a_new_supplier_meet_the_same_one(world: World) -> None:
    first, second = world.resolve(evidence("Nuovo Batch S.r.l."), evidence("NUOVO BATCH SRL"))
    assert first.supplier_id == second.supplier_id and first.created
    assert world.count(Supplier) == 1


def test_resolving_again_changes_nothing(world: World) -> None:
    item = evidence("Uno S.r.l.", vat="01234567890", ibans=(IBAN_A,))
    world.one(item)
    before = snapshot(world)

    again = world.one(item)

    assert again.outcome == Outcome.MATCHED_EXACT_IDENTIFIER and not again.created
    assert snapshot(world) == before


def test_planning_writes_nothing_and_applying_writes_what_was_planned(world: World) -> None:
    plan = world.resolver.plan([evidence("Uno S.r.l.", vat="01234567890", ibans=(IBAN_A,))])
    assert snapshot(world) == (0, 0, 0, 0)  # the plan is only in memory
    assert (len(plan.suppliers), len(plan.identifiers), len(plan.aliases)) == (1, 2, 1)

    world.resolver.apply(plan)

    assert snapshot(world) == (1, 2, 1, 0)


def test_the_resolver_never_reads_another_workspace(
    world: World, db_session: Session, factory: BookingFactory
) -> None:
    mine = world.one(evidence("Uno S.r.l.", vat="01234567890")).supplier_id
    stranger = World(db_session, factory.tenant())

    theirs = stranger.one(evidence("Uno S.r.l.", vat="01234567890"))

    assert theirs.created and theirs.supplier_id != mine  # not matched across tenants
    assert world.count(Supplier) == 1 and stranger.count(Supplier) == 1
    assert stranger.repo.get(mine) is None  # and not even visible


def test_the_resolution_output_carries_kinds_and_ids_never_identifier_values(world: World) -> None:
    world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,)))

    result = world.one(evidence("Uno", vat="01234567890", ibans=(IBAN_A,)))

    text = repr(result)
    for secret in ("01234567890", IBAN_A, DIGEST_A):
        assert secret not in text


def test_resolution_is_deterministic_across_workspaces(
    db_session: Session, factory: BookingFactory
) -> None:
    def run(w: World) -> list[tuple[str, str, int]]:
        w.one(evidence("Rossi Food S.r.l.", vat="01234567890"))
        outcomes = w.resolve(
            evidence("Rossi Food S.r.l.", vat="01234567890"),
            evidence("Rossi Foods S.r.l."),
            evidence("Altro Fornitore"),
            evidence("Rossi Food S.r.l.", vat="09876543210"),
        )
        return [(r.outcome.value, r.method.value, len(r.review_candidate_ids)) for r in outcomes]

    assert run(World(db_session, factory.tenant())) == run(World(db_session, factory.tenant()))


# --- fuzzy similarity: the versioned, documented rule --------------------------------------------


def test_similarity_is_a_deterministic_four_decimal_ratio() -> None:
    assert similarity("rossi food srl", "rossi food srl") == Decimal("1.0000")
    assert similarity("abc", "xyz") == Decimal("0.0000")
    assert similarity("", "") == Decimal(0)
    value = similarity("rossi food srl", "rossi food spa")
    assert value == similarity("rossi food srl", "rossi food spa")
    assert isinstance(value, Decimal) and value.as_tuple().exponent == -4


def test_the_fuzzy_threshold_is_versioned_and_sits_where_the_documentation_says() -> None:
    assert Decimal("0.85") == FUZZY_REVIEW_MIN_SIMILARITY
    assert MAX_REVIEWS_PER_SUPPLIER == 3
    assert RESOLUTION_POLICY_VERSION == "supplier-resolution-v1"
    assert similarity("rossi food srl", "rossi foods srl") >= FUZZY_REVIEW_MIN_SIMILARITY
    assert similarity("rossi food srl", "bianchi arredi srl") < FUZZY_REVIEW_MIN_SIMILARITY
    assert similarity("rossi food srl", "rossi food spa") >= FUZZY_REVIEW_MIN_SIMILARITY


def test_the_fuzzy_match_uses_the_standard_library_only() -> None:
    import app.modules.suppliers.normalization as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from difflib import SequenceMatcher" in source
    for banned in ("rapidfuzz", "fuzzywuzzy", "jellyfish", "sklearn", "numpy", "embedding"):
        assert banned not in source


# --- review invariants (the database is the last line of defence) --------------------------------


def review_values(world: World, provisional: UUID, candidate: UUID, **extra: Any) -> dict[str, Any]:
    return {
        "workspace_id": world.tenant.workspace.id,
        "provisional_supplier_id": provisional,
        "candidate_supplier_id": candidate,
        "reason": ReviewReason.FUZZY_NAME_SIMILARITY,
        "similarity_score": Decimal("0.9000"),
        **extra,
    }


def test_a_supplier_cannot_be_its_own_review_candidate(
    world: World, rejects: Rejects, db_session: Session
) -> None:
    supplier_id = world.one(evidence("Uno")).supplier_id
    with rejects(pg.CheckViolation, "ck_supplier_resolution_reviews_provisional_is_not_candidate"):
        db_session.add(SupplierResolutionReview(**review_values(world, supplier_id, supplier_id)))


def test_a_review_status_and_resolution_time_must_agree(
    world: World, rejects: Rejects, db_session: Session
) -> None:
    one = world.one(evidence("Uno")).supplier_id
    two = world.one(evidence("Zzzz Completamente Diverso")).supplier_id
    with rejects(pg.CheckViolation, "ck_supplier_resolution_reviews_resolved_matches_status"):
        db_session.add(
            SupplierResolutionReview(
                **review_values(world, one, two, status=ReviewStatus.NOT_DUPLICATE)
            )
        )
    with rejects(pg.CheckViolation, "ck_supplier_resolution_reviews_resolved_matches_status"):
        db_session.add(
            SupplierResolutionReview(
                **review_values(world, one, two, resolved_at=datetime.now(UTC))
            )
        )


def test_a_pair_is_reviewed_once(world: World, rejects: Rejects, db_session: Session) -> None:
    one = world.one(evidence("Uno")).supplier_id
    two = world.one(evidence("Zzzz Completamente Diverso")).supplier_id
    db_session.add(SupplierResolutionReview(**review_values(world, one, two)))
    db_session.flush()
    with rejects(pg.UniqueViolation, "uq_supplier_reviews_workspace_id_provisional_candidate"):
        db_session.add(SupplierResolutionReview(**review_values(world, one, two)))


def test_only_pending_reviews_are_created_and_nothing_merges_suppliers(world: World) -> None:
    world.one(evidence("Rossi Food S.r.l.", vat="01234567890"))
    world.one(evidence("Rossi Foods S.r.l."))
    world.one(evidence("Rossi Food S.r.l.", vat="09876543210"))

    reviews = world.repo.list_reviews()

    assert reviews and all(r.status == ReviewStatus.PENDING for r in reviews)
    assert world.count(Supplier) == 3  # a review never removes or merges a supplier
