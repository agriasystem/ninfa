"""Data-source API V1 (Struttura > Fonti dati): what a property's data sources are, how one is set
up, how a file gets in, how a source is switched off.

    GET    .../data-sources                         the five cards' real state
    DELETE .../data-sources/{source_id}             switch a source off (data are kept)
    POST   .../data-sources/import-preview?domain=  look at a file, writes NOTHING
    POST   .../data-sources/imports?domain=         import it (the pilot's own services)
    GET    .../data-sources/templates/{domain}      the column row of the canonical CSV

Smart Import - the hotel's own CSV / Excel file, with the person's matching of its columns:

    POST   .../data-sources/import-inspection?domain=  read a file, propose what each column means
    POST   .../data-sources/import-mapping-check        is this matching enough? (backend's rules)
    POST   .../data-sources/import-validation              judge every row with it (writes NOTHING)
    POST   .../data-sources/imports/mapped              import with it (and remember it on success)
    GET    .../data-sources/{id}/import-configuration   how this source's files are read
    DELETE .../data-sources/{id}/import-configuration   forget it (imported data stays)

There is NO route that creates a source on its own: a source comes to exist only when an import
succeeds (see `DataSourcesService.import_file`), so an abandoned flow never leaves one "configured".

(every path starts with `/api/v1/properties/{property_id}`)

Thin on purpose: authentication, authorization and tenant derivation are `resolve_property_scope`
(the SAME dependency every property route uses, so a missing, archived or foreign property is the
same 404), and everything else is `DataSourcesService`. A file travels as the raw request body (no
multipart: no new dependency) with its name in `?filename=`; it is never stored by this API.
"""

from dataclasses import asdict
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.decisions.deps import PropertyScope, resolve_property_scope
from app.api.v1.sources.schemas import (
    MAX_JSON_BODY_BYTES,
    CapabilityResponse,
    ColumnInfoResponse,
    ConstantSpecResponse,
    DryRunResponse,
    DryRunSummaryResponse,
    FieldSpecResponse,
    FileInspectionResponse,
    FormatHintResponse,
    ImportPreviewResponse,
    ImportResultResponse,
    InvalidRowResponse,
    MappedFileRequest,
    MappedImportRequest,
    MappedImportResultResponse,
    MappingCheckRequest,
    MappingCheckResponse,
    MappingProblemResponse,
    ProfileInfoResponse,
    QuestionResponse,
    RowIssueResponse,
    RowProblemResponse,
    SavedColumnResponse,
    SavedConfigurationResponse,
    SavedConstantResponse,
    SourceCardResponse,
    SourcesOverviewResponse,
    UnderstandingResponse,
    UnderstandRequest,
)
from app.db.session import get_session
from app.modules.data_sources.errors import (
    DataSourceNotFoundError,
    FileTooLargeError,
    InvalidImportRequestError,
    InvalidSnapshotDateError,
    UnsupportedDomainError,
)
from app.modules.data_sources.files import MAX_FILE_BYTES, template_csv
from app.modules.data_sources.mapping_types import (
    DryRun,
    FileInspection,
    MappingCheck,
    SavedConfiguration,
)
from app.modules.data_sources.service import DataSourcesService, MappedImport
from app.modules.data_sources.types import SourcesOverview
from app.modules.data_sources.understanding_redaction import redact_inspection
from app.modules.document_understanding.redaction import PersonalDataGuard
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


async def _read_json[ModelT: BaseModel](request: Request, model: type[ModelT]) -> ModelT:
    """A JSON body (a file travels inside it as base64), refused as soon as it exceeds the maximum
    and never buffered beyond it."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_JSON_BODY_BYTES:
        raise FileTooLargeError(MAX_FILE_BYTES)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_JSON_BODY_BYTES:
            raise FileTooLargeError(MAX_FILE_BYTES)
    try:
        return model.model_validate_json(bytes(body))
    except ValidationError as error:
        raise InvalidImportRequestError() from error


def _inspection_response(inspection: FileInspection) -> FileInspectionResponse:
    # The gate every answer about a file passes before it is serialised: an e-mail address, a
    # telephone number, a tax code or an IBAN never reaches the browser, from whichever service
    # the answer comes (the service that read the file also removes the names it found).
    inspection = redact_inspection(inspection, PersonalDataGuard())
    profile = inspection.profile
    return FileInspectionResponse(
        domain=inspection.domain.value,
        file_type=inspection.file_type,
        problem=inspection.problem.value if inspection.problem else None,
        sheet_name=inspection.sheet_name,
        sheet_names=list(inspection.sheet_names),
        requires_sheet_selection=inspection.requires_sheet_selection,
        columns=[
            ColumnInfoResponse(
                position=column.position,
                header=column.header,
                examples=list(column.examples),
                field=column.field,
                level=column.level.value if column.level else None,
                not_used_reason=column.not_used_reason,
                date_order=column.date_order,
                number_style=column.number_style,
            )
            for column in inspection.columns
        ],
        fields=[
            FieldSpecResponse(
                key=spec.key,
                kind=spec.kind.value,
                constant=(
                    None
                    if spec.constant is None
                    else ConstantSpecResponse(
                        kind=spec.constant.kind.value,
                        choices=list(spec.constant.choices),
                        default=spec.constant.default,
                    )
                ),
            )
            for spec in inspection.fields
        ],
        requirement_groups=[list(group) for group in inspection.requirement_groups],
        suggestion_complete=inspection.suggestion_complete,
        already_canonical=inspection.already_canonical,
        profile=ProfileInfoResponse(
            status=profile.status.value,
            reason=profile.reason.value if profile.reason else None,
            mapping=profile.mapping,
            last_used_at=profile.last_used_at,
            missing_columns=list(profile.missing_columns),
        ),
        already_imported=inspection.already_imported,
        understanding=(
            None
            if inspection.understanding is None
            else UnderstandingResponse.model_validate(asdict(inspection.understanding))
        ),
        proposal=inspection.proposal,
    )


def _check_response(check: MappingCheck) -> MappingCheckResponse:
    return MappingCheckResponse(
        valid=check.valid,
        missing=[list(group) for group in check.missing],
        problems=[
            MappingProblemResponse(code=problem.code, fields=list(problem.fields))
            for problem in check.problems
        ],
    )


def _dry_run_response(result: DryRun) -> DryRunResponse:
    return DryRunResponse(
        status=result.status.value,
        problem=result.problem.value if result.problem else None,
        can_import=result.can_import,
        check=_check_response(result.check) if result.check else None,
        format_hints=[
            FormatHintResponse(
                question=hint.question, proven=hint.proven, columns=list(hint.columns)
            )
            for hint in result.format_hints
        ],
        rows_total=result.rows_total,
        rows_valid=result.rows_valid,
        rows_invalid=result.rows_invalid,
        sample_fields=list(result.sample_fields),
        sample_rows=[list(row) for row in result.sample_rows],
        row_problems=[
            RowProblemResponse(field=item.field, code=item.code, count=item.count)
            for item in result.row_problems
        ],
        invalid_rows=[
            InvalidRowResponse(
                row=row.row,
                issues=[RowIssueResponse(field=field, code=code) for field, code in row.issues],
            )
            for row in result.invalid_rows
        ],
        already_imported=result.already_imported,
        rows_unclassified=result.rows_unclassified,
        summary=(
            None
            if result.summary is None
            else DryRunSummaryResponse.model_validate(asdict(result.summary))
        ),
        questions=[QuestionResponse.model_validate(asdict(q)) for q in result.questions],
    )


def _configuration_response(configuration: SavedConfiguration) -> SavedConfigurationResponse:
    return SavedConfigurationResponse(
        data_source_id=configuration.data_source_id,
        domain=configuration.domain.value,
        columns=[SavedColumnResponse(field=f, column=c) for f, c in configuration.columns],
        constants=[SavedConstantResponse(field=f, value=v) for f, v in configuration.constants],
        last_used_at=configuration.last_used_at,
        schema_current=configuration.schema_current,
    )


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


@router.post(
    "/import-inspection",
    response_model=FileInspectionResponse,
    summary="Read a CSV / Excel file and propose what each column means (writes nothing)",
)
async def inspect_import(
    request: Request,
    domain: DataSourceDomain = Query(..., description="The kind of data the file carries."),
    filename: str = Query(..., min_length=1, max_length=255, description="The file's own name."),
    sheet_name: str | None = Query(None, max_length=200, description="Excel: the sheet to read."),
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> FileInspectionResponse:
    content = await _read_file(request)
    service = DataSourcesService(session, scope.tenant)
    inspection = await run_in_threadpool(
        lambda: service.inspect_file(
            scope.property_id, domain, filename=filename, content=content, sheet_name=sheet_name
        )
    )
    return _inspection_response(inspection)


@router.post(
    "/import-understanding",
    response_model=FileInspectionResponse,
    summary="Understand a whole document and say what is still unclear (writes nothing)",
)
async def understand_import(
    request: Request,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> FileInspectionResponse:
    body = await _read_json(request, UnderstandRequest)
    content = body.content()
    service = DataSourcesService(
        session, scope.tenant, getattr(request.app.state, "import_understanding_resolver", None)
    )
    inspection = await run_in_threadpool(
        lambda: service.understand_file(
            scope.property_id,
            body.domain,
            filename=body.filename,
            content=content,
            answers=body.answers,
            confirmed_domain=body.confirmed_domain,
        )
    )
    return _inspection_response(inspection)


@router.post(
    "/import-mapping-check",
    response_model=MappingCheckResponse,
    summary="Is this matching of columns enough to import? (the backend's own rules)",
)
async def check_import_mapping(
    request: Request,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> MappingCheckResponse:
    body = await _read_json(request, MappingCheckRequest)
    service = DataSourcesService(session, scope.tenant)
    return _check_response(service.check_mapping(body.domain, body.mapping))


@router.post(
    "/import-validation",
    response_model=DryRunResponse,
    summary="Judge every row of a file with this matching, as the import will (writes nothing)",
)
async def dry_run_import(
    request: Request,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> DryRunResponse:
    body = await _read_json(request, MappedFileRequest)
    content = body.content()
    service = DataSourcesService(session, scope.tenant)
    result = await run_in_threadpool(
        lambda: service.dry_run(
            scope.property_id,
            body.domain,
            filename=body.filename,
            content=content,
            mapping=body.mapping,
            period_start=body.period_start,
        )
    )
    return _dry_run_response(result)


@router.post(
    "/imports/mapped",
    response_model=MappedImportResultResponse,
    summary="Import with the person's matching of columns (a source exists only on success)",
)
async def import_mapped_file(
    request: Request,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> MappedImportResultResponse:
    body = await _read_json(request, MappedImportRequest)
    content = body.content()
    service = DataSourcesService(session, scope.tenant)
    outcome = await run_in_threadpool(
        lambda: service.import_file(
            scope.property_id,
            body.domain,
            filename=body.filename,
            content=content,
            snapshot_local_date=body.snapshot_local_date,
            mapped=MappedImport(body.mapping, body.save_configuration, body.period_start),
        )
    )
    return MappedImportResultResponse(
        succeeded=outcome.succeeded,
        problem=outcome.problem.value if outcome.problem else None,
        rows_total=outcome.rows_total,
        rows_invalid=outcome.rows_invalid,
        created=outcome.created,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        already_imported=outcome.already_imported,
        configuration_saved=outcome.configuration_saved,
    )


@router.get(
    "/{data_source_id}/import-configuration",
    response_model=SavedConfigurationResponse,
    summary="How this source's files are read (what was saved)",
)
def get_import_configuration(
    data_source_id: UUID,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> SavedConfigurationResponse:
    configuration = DataSourcesService(session, scope.tenant).saved_configuration(
        scope.property_id, data_source_id
    )
    if configuration is None:
        raise DataSourceNotFoundError()  # nothing saved reads exactly like no such source
    return _configuration_response(configuration)


@router.delete(
    "/{data_source_id}/import-configuration",
    status_code=204,
    response_class=Response,
    summary="Forget how this source's files are read (imported data stays)",
)
def forget_import_configuration(
    data_source_id: UUID,
    scope: PropertyScope = Depends(resolve_property_scope),
    session: Session = Depends(get_session),
) -> Response:
    DataSourcesService(session, scope.tenant).forget_configuration(
        scope.property_id, data_source_id
    )
    return Response(status_code=204)


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
