"""Italian, user-safe words for the few internal vocabularies Mia's tools expose beyond what
`ask_ninfa.semantic_labels` already covers (decision types and statuses, cost and labor categories).
One place, so a tool never hands the model a raw enum value it could echo to the person."""

from app.modules.decisions.coverage import AnalysisDomain
from app.modules.ingestion.models import DataSourceDomain, FileScope, ImportJobStatus

AREA_LABELS: dict[AnalysisDomain, str] = {
    AnalysisDomain.REVENUE: "Ricavi",
    AnalysisDomain.DISTRIBUTION: "Distribuzione",
    AnalysisDomain.COSTS: "Costi",
    AnalysisDomain.LABOR: "Personale",
}

DATA_DOMAIN_LABELS: dict[DataSourceDomain, str] = {
    DataSourceDomain.BOOKINGS: "prenotazioni",
    DataSourceDomain.COSTS: "costi (fatture)",
    DataSourceDomain.LABOR: "personale (ore)",
}

IMPORT_STATUS_LABELS: dict[ImportJobStatus, str] = {
    ImportJobStatus.PENDING: "in attesa",
    ImportJobStatus.RUNNING: "in corso",
    ImportJobStatus.SUCCEEDED: "completato",
    ImportJobStatus.FAILED: "non riuscito",
}

FILE_SCOPE_LABELS: dict[FileScope, str] = {
    FileScope.FULL: "completo (tutto il periodo che copre)",
    FileScope.PARTIAL: "parziale (una parte: un canale, un reparto)",
    FileScope.DELTA: "solo novità o modifiche",
}


def area_label(domain: AnalysisDomain) -> str:
    return AREA_LABELS[domain]


def data_domain_label(domain: DataSourceDomain) -> str:
    return DATA_DOMAIN_LABELS[domain]


def import_status_label(status: ImportJobStatus) -> str:
    return IMPORT_STATUS_LABELS[status]


def file_scope_label(scope: FileScope) -> str:
    return FILE_SCOPE_LABELS[scope]


__all__ = [
    "AREA_LABELS",
    "DATA_DOMAIN_LABELS",
    "FILE_SCOPE_LABELS",
    "IMPORT_STATUS_LABELS",
    "area_label",
    "data_domain_label",
    "file_scope_label",
    "import_status_label",
]
