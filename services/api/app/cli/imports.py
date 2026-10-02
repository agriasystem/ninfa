"""Pilot data import CLI (Gate 21B): triggers the SAME production import services the test suite
exercises - `BookingImportService`, `LaborImportService`, `InvoiceImportService` - against a real
file on disk. Nothing here re-implements parsing, mapping, validation or canonicalisation.

Booking and labor files use ONE canonical pilot CSV convention: the column headers ARE the
service's own canonical field names (`app.modules.bookings.mapping.CanonicalField`,
`app.modules.labor.mapping.LaborField` - e.g. `source_record_id`, `check_in`, `work_date`), dates
are `YYYY-MM-DD` and decimals use `.`. The CLI derives an identity column mapping from whichever
of those names are present as headers and confirms it before every import - there is
deliberately no mapping-suggestion review step and no generic user-configurable mapping engine
(see docs/architecture/pilot-readiness-v1.md, "Data intake"). Invoices are FatturaPA XML, which
the import service already parses directly with no mapping step at all.

    python -m app.cli.imports bookings --workspace-slug h --property-slug h \
        --data-source-id <uuid> --file bookings.csv
    python -m app.cli.imports labor --workspace-slug h --property-slug h \
        --data-source-id <uuid> --file labor.csv --snapshot-local-date 2026-09-29
    python -m app.cli.imports invoices --workspace-slug h --property-slug h \
        --data-source-id <uuid> --file invoice.xml

Every command exits 1 (after printing the machine-readable outcome) when the import did not
succeed: a failed import is never silently "processed".

UNRECOGNIZED-COLUMN WARNING (Gate 24B, bookings/labor only - invoices are FatturaPA XML and have
no header/mapping concept at all): `_identity_column_mapping` already silently drops any header
that fails to normalize-match a canonical field name, whether that header is a genuinely
irrelevant extra column or a typo of an optional one - the two are indistinguishable (no fuzzy/
edit-distance matching exists anywhere in this codebase, and none is added here). Before every
booking/labor import, this module prints one deterministic `WARNING unrecognized_columns=...`
line - never "invalid", never "typo" - when any header does not match a canonical field; it
never changes the exit code (0 on success, exactly as before) and never weakens
`MappingConfig`/`LaborMappingConfig`'s own required-field validation, which still fails closed.
"""

import argparse
import csv
import io
from datetime import date
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.cli._support import resolve_tenant_and_property, run_cli
from app.db.session import get_sessionmaker
from app.modules.bookings.mapping import CanonicalField, normalize_header
from app.modules.bookings.service import BookingImportService
from app.modules.invoices.service import InvoiceImportService
from app.modules.labor.mapping import LaborField
from app.modules.labor.service import LaborImportService

_BOOKING_DATE_FIELDS = (
    CanonicalField.BOOKED_AT,
    CanonicalField.CHECK_IN,
    CanonicalField.CHECK_OUT,
    CanonicalField.CANCELLED_AT,
)


def _identity_column_mapping(
    headers: list[str], fields: type[StrEnum]
) -> dict[str, dict[str, str]]:
    """Map every canonical field whose exact name is present as a header, verbatim, to itself -
    the one pilot convention this CLI supports (see the module docstring). Never a fuzzy or
    suggested mapping."""
    present = {normalize_header(h) for h in headers}
    return {
        field.value: {"column": field.value}
        for field in fields
        if normalize_header(field.value) in present
    }


def _read_headers(content: bytes) -> list[str]:
    """The header row only, exactly as the reader will see it (UTF-8, comma-delimited: the one
    pilot CSV convention - see the module docstring)."""
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    return next(reader, [])


def _unrecognized_columns(headers: list[str], fields: type[StrEnum]) -> list[str]:
    """Gate 24B: every header that does NOT normalize-match any of `fields`' canonical names -
    the exact complement of what `_identity_column_mapping` above maps. Deliberately uses the
    SAME `normalize_header` as every other header comparison in this CLI (no fuzzy/edit-distance
    logic - see the module docstring): a typo of an optional field and a genuinely irrelevant
    extra column are indistinguishable here, on purpose. Original header spelling is kept (never
    the normalized form) since that is what the operator actually wrote and will recognise;
    order is first-occurrence-in-the-file and duplicates are dropped, so the output is
    deterministic and stable for logging/automation."""
    known = {normalize_header(field.value) for field in fields}
    seen: set[str] = set()
    unrecognized: list[str] = []
    for header in headers:
        key = normalize_header(header)
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        unrecognized.append(header)
    return unrecognized


def _print_unrecognized_columns_warning(headers: list[str], fields: type[StrEnum]) -> None:
    """Prints nothing when every header is recognized. Never calls any column "invalid" or a
    "typo" - it states a fact (these headers were not recognized), never a diagnosis of why."""
    unrecognized = _unrecognized_columns(headers, fields)
    if unrecognized:
        print(f"WARNING unrecognized_columns={','.join(unrecognized)}")


def _error_code_str(code: object) -> str:
    if code is None:
        return "-"
    value = getattr(code, "value", None)
    return value if isinstance(value, str) else str(code)


def run_import_bookings(
    session: Session, *, workspace_slug: str, property_slug: str, data_source_id: UUID, file: Path
) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    content = file.read_bytes()
    service = BookingImportService(session, tenant)
    headers = _read_headers(content)
    _print_unrecognized_columns_warning(headers, CanonicalField)
    service.save_mapping(
        data_source_id,
        headers=headers,
        column_mapping=_identity_column_mapping(headers, CanonicalField),
        format_options={
            "delimiter": ",",
            "encoding": "utf-8",
            "date_formats": {field.value: "%Y-%m-%d" for field in _BOOKING_DATE_FIELDS},
            "decimal_separator": ".",
        },
        property_id=prop.id,
    )
    result = service.import_file(
        data_source_id, filename=file.name, content=content, property_id=prop.id
    )
    print(
        f"Booking import: status={result.status.value} "
        f"error_code={_error_code_str(result.error_code)} "
        f"rows_total={result.rows_total} rows_invalid={result.rows_invalid} "
        f"created={result.bookings_created} updated={result.bookings_updated} "
        f"unchanged={result.bookings_unchanged}"
    )
    return 0 if result.succeeded else 1


def run_import_labor(
    session: Session,
    *,
    workspace_slug: str,
    property_slug: str,
    data_source_id: UUID,
    file: Path,
    snapshot_local_date: date,
) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    content = file.read_bytes()
    service = LaborImportService(session, tenant)
    headers = _read_headers(content)
    _print_unrecognized_columns_warning(headers, LaborField)
    service.save_mapping(
        data_source_id,
        headers=headers,
        column_mapping=_identity_column_mapping(headers, LaborField),
        format_options={
            "delimiter": ",",
            "encoding": "utf-8",
            "date_formats": {LaborField.WORK_DATE.value: "%Y-%m-%d"},
            "decimal_separator": ".",
        },
        property_id=prop.id,
    )
    result = service.import_file(
        data_source_id,
        filename=file.name,
        content=content,
        snapshot_local_date=snapshot_local_date,
        property_id=prop.id,
    )
    print(
        f"Labor import: status={result.status.value} "
        f"error_code={_error_code_str(result.error_code)} "
        f"rows_total={result.rows_total} rows_invalid={result.rows_invalid} "
        f"entries_created={result.entries_created} snapshot_reused={result.snapshot_reused}"
    )
    return 0 if result.succeeded else 1


def run_import_invoices(
    session: Session, *, workspace_slug: str, property_slug: str, data_source_id: UUID, file: Path
) -> int:
    tenant, prop = resolve_tenant_and_property(session, workspace_slug, property_slug)
    content = file.read_bytes()
    service = InvoiceImportService(session, tenant)
    result = service.import_file(
        data_source_id, filename=file.name, content=content, property_id=prop.id
    )
    print(
        f"Invoice import: status={result.status.value} "
        f"error_code={_error_code_str(result.error_code)} "
        f"rows_total={result.rows_total} rows_invalid={result.rows_invalid} "
        f"invoices_created={result.invoices_created} unchanged={result.invoices_unchanged} "
        f"suppliers_created={result.suppliers_created} reviews={result.reviews_created}"
    )
    return 0 if result.succeeded else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.imports")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("bookings", "invoices"):
        sub = subparsers.add_parser(name, help=f"Import a {name[:-1]} file for a property.")
        sub.add_argument("--workspace-slug", required=True)
        sub.add_argument("--property-slug", required=True)
        sub.add_argument("--data-source-id", required=True, type=UUID)
        sub.add_argument("--file", required=True, type=Path)

    labor = subparsers.add_parser("labor", help="Import a labor file for a property.")
    labor.add_argument("--workspace-slug", required=True)
    labor.add_argument("--property-slug", required=True)
    labor.add_argument("--data-source-id", required=True, type=UUID)
    labor.add_argument("--file", required=True, type=Path)
    labor.add_argument("--snapshot-local-date", required=True, type=date.fromisoformat)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    with get_sessionmaker()() as session:

        def dispatch() -> int:
            if args.command == "bookings":
                return run_import_bookings(
                    session,
                    workspace_slug=args.workspace_slug,
                    property_slug=args.property_slug,
                    data_source_id=args.data_source_id,
                    file=args.file,
                )
            if args.command == "labor":
                return run_import_labor(
                    session,
                    workspace_slug=args.workspace_slug,
                    property_slug=args.property_slug,
                    data_source_id=args.data_source_id,
                    file=args.file,
                    snapshot_local_date=args.snapshot_local_date,
                )
            return run_import_invoices(
                session,
                workspace_slug=args.workspace_slug,
                property_slug=args.property_slug,
                data_source_id=args.data_source_id,
                file=args.file,
            )

        return run_cli(dispatch)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_import_bookings", "run_import_invoices", "run_import_labor"]
