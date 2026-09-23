"""Gate 6 scope guards: supplier registry, invoices and their ingestion, nothing beyond them.

No cost baseline, CPOR, anomaly or decision; no priority, impact or recommendation; no AI, OCR,
PDF parsing or signed-file support; no supplier merge; no price trend; no public API, worker task
or scheduler; no float; no generic repository; no new third-party dependency.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_root
import app.modules.invoices as invoices_package
import app.modules.suppliers as suppliers_package
from app.db.base import Base

INVOICES_DIR = Path(invoices_package.__file__).parent
SUPPLIERS_DIR = Path(suppliers_package.__file__).parent
APP_DIR = Path(app_root.__file__).parent
WORKER_DIR = Path(__file__).resolve().parents[2] / "worker" / "worker"
ROOT = Path(__file__).resolve().parents[3]
PYPROJECTS = [
    ROOT / "pyproject.toml",
    Path(__file__).resolve().parents[1] / "pyproject.toml",
    Path(__file__).resolve().parents[2] / "worker" / "pyproject.toml",
]
DOCS = ROOT / "docs" / "architecture"

INVOICE_MODULES = {
    "__init__",
    "canonical",
    "classification",
    "cost_categories",
    "documents",
    "errors",
    "fatturapa",
    "mapping",
    "models",
    "repository",
    "service",
    "structured",
}
SUPPLIER_MODULES = {
    "__init__",
    "errors",
    "models",
    "normalization",
    "repository",
    "resolution",
}
SOURCES = sorted([*INVOICES_DIR.glob("*.py"), *SUPPLIERS_DIR.glob("*.py")])

# Whole words (identifiers are split on snake_case and CamelCase before comparing).
FORBIDDEN_TOKENS = {
    "cpor",
    "anomaly",
    "anomalies",
    "baseline",
    "forecast",
    "trend",
    "inflation",
    "recommendation",
    "recommend",
    "embedding",
    "vector",
    "llm",
    "openai",
    "anthropic",
    "prompt",
    "ocr",
    "tesseract",
    "pypdf",
    "pdfminer",
    "pdfplumber",
    "pandas",
    "numpy",
    "polars",
    "lxml",
    "defusedxml",
    "narrative",
}
FORBIDDEN_CLASSES = {
    "Decision",
    "DecisionFact",
    "DecisionEvent",
    "DecisionOutcome",
    "CostBaseline",
    "CostDailyMetric",
    "CostAnomaly",
    "Priority",
    "Impact",
    "Recommendation",
    "BaseRepository",
    "GenericRepository",
    "SupplierMerge",
}
FORBIDDEN_TABLE_WORDS = ("decision", "baseline_cost", "cost_baseline", "anomal", "cpor", "priority")


def identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.update(node.name.split("."))
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def tokens(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return {part.lower() for part in spaced.split("_") if part}


# --- the packages are the explicit set of modules ---------------------------------------------


def test_the_packages_are_the_explicit_set_of_modules() -> None:
    assert {p.stem for p in INVOICES_DIR.glob("*.py")} == INVOICE_MODULES
    assert {p.stem for p in SUPPLIERS_DIR.glob("*.py")} == SUPPLIER_MODULES
    assert not [p for p in INVOICES_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_forbidden_vocabulary_in_the_gate_6_code(path: Path) -> None:
    found = {
        word for name in identifiers(path) for word in tokens(name) if word in FORBIDDEN_TOKENS
    }
    assert found == set(), found


def test_no_forbidden_class_exists_anywhere() -> None:
    classes = {
        node.name
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }
    assert classes & FORBIDDEN_CLASSES == set()


def test_the_schema_gained_no_decision_cost_baseline_or_anomaly_table() -> None:
    names = " ".join(sorted(Base.metadata.tables))
    for word in FORBIDDEN_TABLE_WORDS:
        assert word not in names, word
    gate_6 = {
        "suppliers",
        "supplier_identifiers",
        "supplier_aliases",
        "supplier_resolution_reviews",
        "invoices",
        "invoice_lines",
        "invoice_mapping_profiles",
        "invoice_import_rows",
    }
    assert gate_6 <= set(Base.metadata.tables)
    # "labor_" is no longer forbidden: Gate 8 legitimately owns that prefix (labor ingestion).
    assert not [t for t in Base.metadata.tables if t.startswith(("cost_", "decision"))]


def test_there_is_no_supplier_merge_and_no_way_to_move_an_invoice_between_suppliers() -> None:
    functions = {
        node.name
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert not [f for f in functions if "merge" in f.lower() or "reassign" in f.lower()]
    assert not [f for f in functions if "move" in f.lower() and "invoice" in f.lower()]


def test_no_review_can_be_resolved_in_this_gate() -> None:
    """Reviews are only ever created PENDING: nothing in the code sets another status."""
    for path in SOURCES:
        if path.name == "models.py":  # the closed set of statuses is declared there
            continue
        text = path.read_text(encoding="utf-8")
        for word in ("CONFIRMED_DUPLICATE", "NOT_DUPLICATE", "resolved_at"):
            assert word not in text, (path.name, word)


# --- no PDF, OCR, signed files ----------------------------------------------------------------


def test_no_pdf_ocr_or_signed_file_library_is_imported_or_declared() -> None:
    for path in SOURCES:
        for name in identifiers(path):
            assert name.lower() not in {"fitz", "pypdf", "pypdf2", "pytesseract", "easyocr", "cv2"}
    for manifest in PYPROJECTS:
        text = manifest.read_text(encoding="utf-8").lower()
        for library in ("pypdf", "pdfminer", "pdfplumber", "pymupdf", "tesseract", "easyocr"):
            assert library not in text, (manifest.name, library)


def test_the_supported_file_types_are_exactly_xml_csv_and_xlsx() -> None:
    from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError
    from app.modules.invoices.service import detect_source

    assert [detect_source(n, b"") for n in ("a.xml", "a.CSV", "a.XLSX")] == ["xml", "csv", "xlsx"]
    for name in ("a.pdf", "a.xml.p7m", "a.p7m", "a.png", "a.jpg", "a.tiff", "a.xls", "a.zip", "a"):
        with pytest.raises(InvoiceImportError) as error:
            detect_source(name, b"")
        assert error.value.error_code == InvoiceErrorCode.UNSUPPORTED_FILE_TYPE, name


# --- read-only where it must be, no float -----------------------------------------------------


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_gate_6_code_computes_no_float(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", path.name
        if isinstance(node, ast.arg) and isinstance(node.annotation, ast.Name):
            assert node.annotation.id != "float", path.name
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float), path.name


def test_the_only_float_the_code_mentions_is_the_type_check_of_a_spreadsheet_cell() -> None:
    """An Excel double is read through its shortest repr, never through binary arithmetic."""
    mentions = [
        path.name
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name) and node.id == "float"
    ]
    assert set(mentions) <= {"structured.py"}


def test_the_services_have_no_web_framework_dependency() -> None:
    code = (
        "import sys, app.modules.invoices.service, app.modules.suppliers.resolution; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "[]"


def test_the_supplier_resolver_is_separate_from_the_import_service() -> None:
    service = (INVOICES_DIR / "service.py").read_text(encoding="utf-8")
    resolution = (SUPPLIERS_DIR / "resolution.py").read_text(encoding="utf-8")
    assert "class SupplierResolver" in resolution
    assert "class SupplierResolver" not in service
    assert "fastapi" not in resolution and "InvoiceImportService" not in resolution


def test_repositories_are_explicit_and_none_is_a_generic_crud_base() -> None:
    for path in (INVOICES_DIR / "repository.py", SUPPLIERS_DIR / "repository.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert not node.bases, (path.name, node.name)  # no inheritance, no generic base
                assert "[" not in ast.unparse(node).split("\n", 1)[0], node.name  # no Generic[T]


def test_every_repository_query_is_tenant_scoped() -> None:
    for path in (INVOICES_DIR / "repository.py", SUPPLIERS_DIR / "repository.py"):
        text = path.read_text(encoding="utf-8")
        assert "self._tenant.workspace_id" in text
        calls = {
            node.func.attr
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "commit" not in calls and "rollback" not in calls  # they flush, never commit


# --- no API, no worker, no dependency ---------------------------------------------------------


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])
    assert paths == ["/api/v1/health"]
    for word in ("supplier", "invoice", "cost", "import", "review", "fattura"):
        assert not [p for p in paths if word in p]


def test_no_router_or_endpoint_was_added_by_the_gate_6_modules() -> None:
    for path in SOURCES:
        assert not {"APIRouter", "FastAPI", "Depends"} & identifiers(path), path.name


def test_no_worker_task_and_no_scheduler_was_added() -> None:
    for word in ("invoice", "supplier", "fattura", "cost"):
        assert not any(
            word in path.read_text(encoding="utf-8").lower() for path in WORKER_DIR.glob("*.py")
        ), word
    tasks = (WORKER_DIR / "tasks.py").read_text(encoding="utf-8")
    assert tasks.count("@app.task") == 1  # still only the Gate 0 heartbeat


def test_only_the_standard_library_sqlalchemy_pydantic_and_the_app_are_imported() -> None:
    allowed_roots = {"app", "sqlalchemy", "pydantic", "__future__"}
    stdlib = set(sys.stdlib_module_names)
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] in stdlib | allowed_roots, (path.name, module)


def test_the_xml_reader_uses_the_standard_library_and_the_dependency_set_is_unchanged() -> None:
    for manifest in PYPROJECTS:
        text = manifest.read_text(encoding="utf-8").lower()
        for library in (
            "numpy",
            "pandas",
            "polars",
            "scipy",
            "scikit",
            "sklearn",
            "openai",
            "anthropic",
            "langchain",
            "defusedxml",
            "lxml",
            "rapidfuzz",
            "fuzzywuzzy",
            "xmlschema",
        ):
            assert library not in text, (manifest.name, library)
    api = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "openpyxl" in api  # the only spreadsheet dependency, present since Gate 2


# --- the documentation states the decisions ---------------------------------------------------


def test_the_documentation_records_the_gate_6_decisions() -> None:
    guide = " ".join((DOCS / "cost-ingestion-v1.md").read_text("utf-8").split())
    for phrase in (
        "Gate 6 V1 supports FatturaPA XML, structured CSV and structured XLSX",
        "PDF, scanned documents (OCR) and signed .p7m files are NOT supported",
        "workspace-wide",
        "VAT number, then tax code, then IBAN hash, then exact name",
        "The raw IBAN is never stored",
        "A fuzzy match never merges two suppliers",
        "supplier-resolution-v1",
        "The data source is not part of the invoice identity",
        "INVOICE_DOCUMENT_CONFLICT",
        "SUPPLIER_IDENTITY_CONFLICT",
        "MULTIPLE_PAYMENT_DUE_DATES",
        "A credit note is stored with negative amounts",
        "cost-classification-v1",
        "provenance, not a probability",
        "all or nothing",
    ):
        assert phrase in guide, phrase
    adr = " ".join(
        (DOCS / "adr" / "0012-invoice-ingestion-and-supplier-resolution-v1.md")
        .read_text("utf-8")
        .split()
    )
    for phrase in (
        "Supplier is workspace-wide",
        "VAT number > tax code > IBAN hash > exact name",
        "No raw IBAN",
        "Fuzzy matching never merges",
        "Invoice identity does not include the data source",
        "Invoices are immutable",
        "Credit notes are signed",
        "Atomic import",
        "PDF, OCR and .p7m are out of V1",
        "Deterministic classification",
    ):
        assert phrase in adr, phrase


def test_the_data_model_and_architecture_documents_mention_the_gate_6_tables() -> None:
    model = (DOCS / "data-model-v1.md").read_text("utf-8")
    for table in (
        "suppliers",
        "supplier_identifiers",
        "supplier_aliases",
        "supplier_resolution_reviews",
        "invoices",
        "invoice_lines",
        "invoice_mapping_profiles",
        "invoice_import_rows",
    ):
        assert table in model, table
    architecture = (DOCS / "architecture-v1.md").read_text("utf-8")
    assert "Gate 6" in architecture and "cost-ingestion-v1" in architecture
