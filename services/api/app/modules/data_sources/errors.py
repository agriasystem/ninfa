"""Stable error codes of the data-source API. The messages are for a person reading a log, never for
the page: the page words every outcome itself, from the code."""

from http import HTTPStatus

from app.core.exceptions import AppError


class DataSourceNotFoundError(AppError):
    """No ACTIVE source of this property has that id. A source of another property or another
    workspace answers exactly the same: which ids exist is never revealed."""

    def __init__(self) -> None:
        super().__init__(
            "DATA_SOURCE_NOT_FOUND", "Data source not found", status_code=HTTPStatus.NOT_FOUND
        )


class AmbiguousSourceError(AppError):
    """The property has several ACTIVE sources of this domain (set up outside this API): NINFA
    keeps ONE per domain, because an analysis reads a domain from exactly one source and never
    picks between several - so it does not pick one to import into either."""

    def __init__(self) -> None:
        super().__init__(
            "SEVERAL_SOURCES",
            "This property has several active sources for this kind of data",
            status_code=HTTPStatus.CONFLICT,
        )


class ImportInProgressError(AppError):
    """Another import of this kind of data, for this property, is still running and did not finish
    within the wait. Nothing was changed: the caller can simply try again."""

    def __init__(self) -> None:
        super().__init__(
            "IMPORT_IN_PROGRESS",
            "Another import of this kind of data is already running for this property",
            status_code=HTTPStatus.CONFLICT,
        )


class UnresolvedImportQuestionsError(AppError):
    """The decision came from NINFA's understanding of the file, and read again with the answers it
    carries that understanding is not READY: a question is still open (or something refuses the
    import). Posting the proposal again, copying the suggested matching or declaring it confirmed
    changes nothing - the questions are answered, and the answers checked, by the server. Nothing
    was written."""

    def __init__(self, level: str, questions: list[str], blockers: list[str]) -> None:
        super().__init__(
            "UNRESOLVED_IMPORT_QUESTIONS",
            "NINFA still has questions about this file: answer them before importing",
            status_code=HTTPStatus.CONFLICT,
            details={"level": level, "questions": questions, "blockers": blockers},
        )


class ImportDecisionChangedError(AppError):
    """A decision that says it comes from NINFA's understanding was changed. A matching the person
    builds by hand is imported without that reference; one that carries it must be the server's
    own, unaltered. Nothing was written."""

    def __init__(self) -> None:
        super().__init__(
            "IMPORT_DECISION_CHANGED",
            "The matching is not the one NINFA settled for these answers",
            status_code=HTTPStatus.CONFLICT,
        )


class InvalidImportRequestError(AppError):
    """The body of an import request is not what the page sends (not JSON of the expected shape, or
    a file that is not valid base64). Nothing was read into NINFA."""

    def __init__(self) -> None:
        super().__init__(
            "INVALID_IMPORT_REQUEST",
            "The import request is not valid",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class UnsupportedDomainError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "UNSUPPORTED_DOMAIN",
            "There is no file template for this kind of data",
            status_code=HTTPStatus.NOT_FOUND,
        )


class FileTooLargeError(AppError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            "FILE_TOO_LARGE",
            "The file is larger than the supported maximum",
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            details={"max_bytes": max_bytes},
        )


class InvalidSnapshotDateError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "INVALID_SNAPSHOT_DATE",
            "snapshot_local_date must be an ISO date (YYYY-MM-DD)",
            status_code=HTTPStatus.BAD_REQUEST,
        )


__all__ = [
    "AmbiguousSourceError",
    "DataSourceNotFoundError",
    "FileTooLargeError",
    "ImportInProgressError",
    "InvalidImportRequestError",
    "InvalidSnapshotDateError",
    "UnsupportedDomainError",
]
