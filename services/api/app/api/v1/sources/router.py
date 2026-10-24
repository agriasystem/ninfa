"""Data-source API V1 (Struttura > Fonti dati): what a property's data sources are, how one is set
up, how a file gets in, how a source is switched off.

    GET    .../data-sources                         the five cards' real state
    DELETE .../data-sources/{source_id}             switch a source off (data are kept)
    POST   .../data-sources/import-preview?domain=  look at a file, writes NOTHING
    POST   .../data-sources/imports?domain=         import it (the pilot's own services)
    GET    .../data-sources/templates/{domain}      the column row of the canonical CSV

There is NO route that creates a source on its own: a source comes to exist only when an import
succeeds (see `DataSourcesService.import_file`), so an abandoned flow never leaves one "configured".

(every path starts with `/api/v1/properties/{property_id}`)

Thin on purpose: authentication, authorization and tenant derivation are `resolve_property_scope`
(the SAME dependency every property route uses, so a missing, archived or foreign property is the
same 404), and everything else is `DataSourcesService`. A file travels as the raw request body (no
multipart: no new dependency) with its name in `?filename=`; it is never stored by this API.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.api.v1.sources.schemas import (
    CapabilityResponse,
    ImportPreviewResponse,
    ImportResultResponse,
    SourceCardResponse,
    SourcesOverviewResponse,
)
from app.db.session import get_session
from app.modules.data_sources.errors import (
    FileTooLargeError,
    InvalidSnapshotDateError,
    UnsupportedDomainError,
)
from app.modules.data_sources.files import MAX_FILE_BYTES, template_csv
from app.modules.data_sources.service import DataSourcesService
from app.modules.data_sources.types import SourcesOverview
from app.modules.ingestion.models import DataSourceDomain

router = APIRouter(prefix="/properties/{property_id}/data-sources", tags=["data-sources"])


def _overview_response(overview: SourcesOverview) -> SourcesOverviewResponse:
    return SourcesOverviewResponse(
        property_id=overview.property_id,
        cards=[
            SourceCardResponse(
                card=card.card.value,
                state=card.state.value,
                domain=card.domain.value if card.domain else None,
                data_source_id=card.data_source_id,
                method=card.method.value if card.method else None,
                last_update_at=card.last_update_at,
                several_sources=card.several_sources,
                derived_from=card.derived_from.value if card.derived_from else None,
                provider=card.provider,
                channels=list(card.channels),
            )
            for card in overview.cards
        ],
        capabilities=[
            CapabilityResponse(domain=item.domain.value, methods=[m.value for m in item.methods])
            for item in overview.capabilities
        ],
        automatic_integrations=list(overview.automatic_integrations),
    )


async def _read_file(request: Request) -> bytes:
    """The raw body, refused as soon as it exceeds the maximum (never buffered beyond it)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise FileTooLargeError(MAX_FILE_BYTES)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FILE_BYTES:
            raise FileTooLargeError(MAX_FILE_BYTES)
    return bytes(body)


@router.get("", response_model=SourcesOverviewResponse, summary="Data sources of a property")
def get_data_sources(
    response: Response,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> SourcesOverviewResponse:
    response.headers["Cache-Control"] = "no-store"
    overview = DataSourcesService(session, scope.tenant).overview(scope.property_id)
    return _overview_response(overview)


@router.delete(
    "/{data_source_id}", status_code=204, response_class=Response, summary="Switch a source off"
)
def deactivate_data_source(
    data_source_id: UUID,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> Response:
    DataSourcesService(session, scope.tenant).deactivate(scope.property_id, data_source_id)
    return Response(status_code=204)


@router.post(
    "/import-preview",
    response_model=ImportPreviewResponse,
    summary="Look at a file before importing it (writes nothing)",
)
async def preview_import(
    request: Request,
    domain: DataSourceDomain = Query(..., description="The kind of data the file carries."),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> ImportPreviewResponse:
    content = await _read_file(request)
    service = DataSourcesService(session, scope.tenant)
    preview = await run_in_threadpool(service.preview, scope.property_id, domain, content)
    return ImportPreviewResponse(
        method=preview.method.value,
        can_import=preview.can_import,
        problem=preview.problem.value if preview.problem else None,
        rows_total=preview.rows_total,
        recognized_columns=list(preview.recognized_columns),
        missing_columns=[list(group) for group in preview.missing_columns],
        unrecognized_columns=list(preview.unrecognized_columns),
        sample_columns=list(preview.sample_columns),
        sample_rows=[list(row) for row in preview.sample_rows],
        documents_with_issues=preview.documents_with_issues,
        already_imported=preview.already_imported,
    )


@router.post(
    "/imports",
    response_model=ImportResultResponse,
    summary="Import a file (the source exists only if the import succeeds)",
)
async def import_file(
    request: Request,
    domain: DataSourceDomain = Query(..., description="The kind of data the file carries."),
    filename: str = Query(..., min_length=1, max_length=255, description="The file's own name."),
    snapshot_local_date: str | None = Query(
        None,
        description="Labor only: the property-local day the file is dated as of (YYYY-MM-DD).",
    ),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> ImportResultResponse:
    parsed_date: date | None = None
    if snapshot_local_date is not None:
        try:
            parsed_date = date.fromisoformat(snapshot_local_date)
        except ValueError as error:
            raise InvalidSnapshotDateError() from error
    content = await _read_file(request)
    service = DataSourcesService(session, scope.tenant)
    outcome = await run_in_threadpool(
        lambda: service.import_file(
            scope.property_id,
            domain,
            filename=filename,
            content=content,
            snapshot_local_date=parsed_date,
        )
    )
    return ImportResultResponse(
        succeeded=outcome.succeeded,
        problem=outcome.problem.value if outcome.problem else None,
        rows_total=outcome.rows_total,
        rows_invalid=outcome.rows_invalid,
        created=outcome.created,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        already_imported=outcome.already_imported,
    )


@router.get("/templates/{domain}", summary="The column row of the canonical CSV of a domain")
def get_template(
    domain: DataSourceDomain,
    scope: PropertyScope = Depends(resolve_property_scope),
) -> Response:
    if domain == DataSourceDomain.COSTS:
        # Costs arrive as FatturaPA XML straight from the accounting software: there is no CSV.
        raise UnsupportedDomainError()
    filename = (
        "modello-prenotazioni.csv"
        if domain == DataSourceDomain.BOOKINGS
        else "modello-personale.csv"
    )
    return Response(
        content=template_csv(domain),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
