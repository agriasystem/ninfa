"""Pydantic layer: normalisation and validation of the input schemas (no database needed)."""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.modules.identity.schemas import UserCreate, UserRead
from app.modules.ingestion.schemas import (
    DataSourceCreate,
    DataSourceRead,
    ImportFileCreate,
    ImportFileRead,
    ImportJobCreate,
    ImportJobRead,
)
from app.modules.properties.schemas import PropertyCreate, PropertyRead
from app.modules.tenancy.schemas import (
    MembershipCreate,
    MembershipRead,
    WorkspaceCreate,
    WorkspaceRead,
)
from tests.support import Factory, Tenant

# --- email -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("  Mario.Rossi@Example.COM ", "mario.rossi@example.com"),
        ("ANNA+tag@Sub.Example.co.uk", "anna+tag@sub.example.co.uk"),
        ("already@lower.it", "already@lower.it"),
    ],
)
def test_email_is_trimmed_and_lowercased(raw: str, stored: str) -> None:
    assert UserCreate(email=raw).email == stored


@pytest.mark.parametrize(
    "email",
    [
        "",
        "plain",
        "a@b",
        "a b@example.com",
        "a@@example.com",
        "@example.com",
        "a@example.",
        "x" * 250 + "@e.com",
    ],
)
def test_invalid_emails_are_rejected(email: str) -> None:
    with pytest.raises(ValidationError):
        UserCreate(email=email)


def test_user_input_cannot_carry_a_password_or_any_unknown_field() -> None:
    with pytest.raises(ValidationError) as info:
        UserCreate(email="a@example.com", password="secret")  # type: ignore[call-arg]

    assert info.value.errors()[0]["type"] == "extra_forbidden"


def test_display_name_is_trimmed_and_may_not_be_blank() -> None:
    assert UserCreate(email="a@example.com", display_name="  Anna ").display_name == "Anna"
    with pytest.raises(ValidationError):
        UserCreate(email="a@example.com", display_name="   ")


# --- slug / name -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "stored"),
    [(" My-Hotel ", "my-hotel"), ("VILLA-ROSA-2", "villa-rosa-2"), ("ab", "ab"), ("a1", "a1")],
)
def test_slug_is_trimmed_and_lowercased(raw: str, stored: str) -> None:
    assert WorkspaceCreate(name="X", slug=raw).slug == stored
    assert PropertyCreate(name="X", slug=raw).slug == stored


@pytest.mark.parametrize(
    "slug", ["", "a", "-x", "x-", "a--b", "a_b", "a b", "hôtel", "x" * 64, "a/b", "a.b"]
)
def test_invalid_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreate(name="X", slug=slug)
    with pytest.raises(ValidationError):
        PropertyCreate(name="X", slug=slug)


def test_names_are_trimmed_and_bounded() -> None:
    assert WorkspaceCreate(name="  Acme  ", slug="acme").name == "Acme"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValidationError):
            WorkspaceCreate(name=bad, slug="acme")


# --- property timezone and currency ----------------------------------------------------------


@pytest.mark.parametrize(
    "timezone", ["Europe/Rome", "UTC", "America/New_York", "Asia/Kolkata", "Europe/London"]
)
def test_valid_iana_timezones_are_accepted(timezone: str) -> None:
    assert PropertyCreate(name="P", slug="pp", timezone=timezone).timezone == timezone


@pytest.mark.parametrize(
    "timezone",
    ["", "Mars/Olympus", "europe/rome", "Europe/Rome/Extra", "CEST", "+02:00", "../etc/passwd"],
)
def test_invalid_timezones_are_rejected(timezone: str) -> None:
    with pytest.raises(ValidationError):
        PropertyCreate(name="P", slug="pp", timezone=timezone)


def test_timezone_is_trimmed() -> None:
    assert PropertyCreate(name="P", slug="pp", timezone=" Europe/Rome ").timezone == "Europe/Rome"


@pytest.mark.parametrize(
    ("raw", "stored"), [("EUR", "EUR"), ("eur", "EUR"), (" usd ", "USD"), ("Chf", "CHF")]
)
def test_currency_is_normalised_to_uppercase(raw: str, stored: str) -> None:
    assert PropertyCreate(name="P", slug="pp", currency=raw).currency == stored


@pytest.mark.parametrize(
    "currency", ["", "EU", "EURO", "E1R", "ZZZ", "XAU", "€€€", "123", "eu r", "GBPP"]
)
def test_invalid_currencies_are_rejected(currency: str) -> None:
    with pytest.raises(ValidationError):
        PropertyCreate(name="P", slug="pp", currency=currency)


def test_property_defaults_are_rome_and_euro() -> None:
    prop = PropertyCreate(name="P", slug="pp")

    assert (prop.timezone, prop.currency) == ("Europe/Rome", "EUR")


# --- tenant scope must never come from a payload ---------------------------------------------


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (WorkspaceCreate, {"name": "X", "slug": "xx", "id": str(uuid4())}),
        (PropertyCreate, {"name": "X", "slug": "xx", "workspace_id": str(uuid4())}),
        (
            MembershipCreate,
            {"user_id": str(uuid4()), "role": "OWNER", "workspace_id": str(uuid4())},
        ),
        (
            DataSourceCreate,
            {
                "property_id": str(uuid4()),
                "name": "X",
                "domain": "COSTS",
                "workspace_id": str(uuid4()),
            },
        ),
        (ImportJobCreate, {"data_source_id": str(uuid4()), "workspace_id": str(uuid4())}),
        (ImportJobCreate, {"data_source_id": str(uuid4()), "property_id": str(uuid4())}),
        (ImportFileCreate, {"original_filename": "a.csv", "workspace_id": str(uuid4())}),
    ],
)
def test_create_schemas_reject_client_supplied_tenant_columns(
    schema: type[BaseModel], payload: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError) as info:
        schema.model_validate(payload)

    assert {error["type"] for error in info.value.errors()} == {"extra_forbidden"}


# --- enums and import file metadata ----------------------------------------------------------


def test_roles_domains_and_source_types_are_closed_sets() -> None:
    with pytest.raises(ValidationError):
        MembershipCreate(user_id=uuid4(), role="SUPERUSER")
    with pytest.raises(ValidationError):
        DataSourceCreate(property_id=uuid4(), name="X", domain="PAYROLL")
    with pytest.raises(ValidationError):
        DataSourceCreate(
            property_id=uuid4(),
            name="X",
            domain="COSTS",
            source_type="PMS_API",
        )


def test_data_source_defaults_to_file_upload() -> None:
    source = DataSourceCreate(property_id=uuid4(), name="X", domain="BOOKINGS")

    assert source.source_type == "FILE_UPLOAD"


def test_import_file_size_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        ImportFileCreate(original_filename="a.csv", size_bytes=-1)
    assert ImportFileCreate(original_filename="a.csv", size_bytes=0).size_bytes == 0
    assert ImportFileCreate(original_filename="a.csv").size_bytes is None


def test_sha256_is_normalised_to_lowercase_hex() -> None:
    assert ImportFileCreate(original_filename="a.csv", sha256="AB" * 32).sha256 == "ab" * 32
    for bad in ("ab" * 31, "zz" * 32, "ab" * 33):
        with pytest.raises(ValidationError):
            ImportFileCreate(original_filename="a.csv", sha256=bad)


# --- read schemas mirror the ORM -------------------------------------------------------------


def test_read_schemas_serialise_orm_rows(
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, _ = two_tenants

    assert WorkspaceRead.model_validate(a.workspace).slug == a.workspace.slug
    assert PropertyRead.model_validate(a.property).workspace_id == a.workspace.id
    assert DataSourceRead.model_validate(a.data_source).property_id == a.property.id
    job = ImportJobRead.model_validate(a.import_job)
    assert (job.status, job.workspace_id) == ("PENDING", a.workspace.id)
    assert job.started_at is None and job.error_code is None


def test_user_membership_and_file_read_schemas(
    factory: Factory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    user = factory.user("read.me@example.com")
    membership = factory.membership(a.workspace, user)
    import_file = factory.import_file(a.import_job, "cd" * 32)

    assert UserRead.model_validate(user).email == "read.me@example.com"
    assert MembershipRead.model_validate(membership).role == "MEMBER"
    assert ImportFileRead.model_validate(import_file).sha256 == "cd" * 32
