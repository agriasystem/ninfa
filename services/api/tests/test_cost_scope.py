"""Gate 7 scope guards: ONE explicit detector (COST_CPOR_ANOMALY) and its evaluation, nothing more.

No table, no migration, no dependency, no API, no worker task; no persisted Decision, priority,
recommendation, budget, forecast, supplier price anomaly, AI or currency conversion; read-only; no
float; no clock.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

import app as app_root
import app.modules.intelligence.costs as costs_package
from app.db.base import Base
from tests.support import alembic_config

PACKAGE_DIR = Path(costs_package.__file__).parent
APP_DIR = Path(app_root.__file__).parent
WORKER_DIR = Path(__file__).resolve().parents[2] / "worker" / "worker"
ROOT = Path(__file__).resolve().parents[3]
PYPROJECTS = [
    ROOT / "pyproject.toml",
    Path(__file__).resolve().parents[1] / "pyproject.toml",
    Path(__file__).resolve().parents[2] / "worker" / "pyproject.toml",
]
DOCS = ROOT / "docs" / "architecture"
MODULES = {
    "__init__",
    "aggregation",
    "confidence",
    "detector",
    "errors",
    "fingerprint",
    "occupancy",
    "periods",
    "precision",
    "repository",
    "selection",
    "service",
    "statistics",
    "types",
}
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))
# Whole words (identifiers are split on snake_case and CamelCase before comparing).
FORBIDDEN_TOKENS = {
    "recommendation",
    "recommend",
    "priority",
    "urgency",
    "actionability",
    "pricing",
    "price",
    "supplier",
    "budget",
    "forecast",
    "trend",
    "prediction",
    "predict",
    "llm",
    "openai",
    "anthropic",
    "prompt",
    "narrative",
    "embedding",
    "vector",
    "weather",
    "competitor",
    "alert",
    "outcome",
    "memory",
    "engine",
    "plugin",
    "registry",
    "dsl",
    "generic",
    "saving",
    "savings",
    "loss",
    "impact",
    "fx",
    "forex",
    "exchange",
    "accrual",
    "labor",
    "labour",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
}
FORBIDDEN_CLASSES = {
    "Decision",
    "DecisionFact",
    "DecisionEvent",
    "DecisionOutcome",
    "DecisionMemory",
    "GenericDecisionEngine",
    "GenericAnomalyEngine",
    "RulesDSL",
    "Priority",
    "Impact",
    "Recommendation",
    "CostBaseline",
    "CostDailyMetric",
    "CostAnomaly",
    "CostMetric",
    "SupplierPriceAnomaly",
}
# Every table of the schema after Gate 6: Gate 7 adds none.
KNOWN_TABLES = {
    "users",
    "workspaces",
    "workspace_memberships",
    "properties",
    "data_sources",
    "import_jobs",
    "import_files",
    "booking_channels",
    "booking_mapping_profiles",
    "bookings",
    "booking_import_rows",
    "room_inventory_daily",
    "booking_snapshots",
    "booking_expected_baselines",
    "booking_expected_comparables",
    "suppliers",
    "supplier_identifiers",
    "supplier_aliases",
    "supplier_resolution_reviews",
    "invoices",
    "invoice_lines",
    "invoice_mapping_profiles",
    "invoice_import_rows",
    # Gate 8 (labor ingestion), unrelated to cost intelligence but present in the same schema.
    "labor_snapshots",
    "labor_entries",
    "labor_mapping_profiles",
    "labor_import_rows",
}
WRITER_ATTRIBUTES = {
    "commit",
    "rollback",
    "flush",
    "add_all",
    "delete",
    "merge",
    "bulk_save_objects",
    "bulk_insert_mappings",
    "bulk_update_mappings",
    "begin",
    "begin_nested",
}
WRITER_IMPORTS = {"insert", "update", "delete", "pg_insert", "text", "Session"}
CLOCK_ATTRIBUTES = {"now", "today", "utcnow", "time", "monotonic", "perf_counter", "fromtimestamp"}


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


# --- the package is the explicit set of modules ---------------------------------------------------


def test_the_package_is_the_explicit_set_of_modules() -> None:
    assert {p.stem for p in SOURCES} == MODULES
    assert not [p for p in PACKAGE_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_forbidden_vocabulary_in_the_cost_code(path: Path) -> None:
    found = {w for name in identifiers(path) for w in tokens(name) if w in FORBIDDEN_TOKENS}
    assert found == set(), found


def test_no_persisted_decision_model_or_generic_engine_exists_anywhere() -> None:
    classes = {
        node.name
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }
    assert classes & FORBIDDEN_CLASSES == set()


def test_there_is_exactly_one_detector_and_one_decision_type() -> None:
    from app.modules.intelligence.costs.types import CostDecisionType

    assert [t.value for t in CostDecisionType] == ["COST_CPOR_ANOMALY"]
    functions = {
        node.name
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    assert {f for f in functions if f.startswith("evaluate_")} >= {
        "evaluate_cpor_anomaly",
    }
    assert not {f for f in functions if "supplier" in f or "budget" in f or "trend" in f}


# --- no database change ---------------------------------------------------------------------------


def test_the_schema_gained_no_table() -> None:
    assert set(Base.metadata.tables) == KNOWN_TABLES


def test_there_is_no_migration_for_gate_7() -> None:
    script = ScriptDirectory.from_config(alembic_config("postgresql+psycopg://unused/unused"))
    revisions = {rev.revision: rev.down_revision for rev in script.walk_revisions()}
    # Gate 7 added no migration: Gate 6's 0007 is directly followed by Gate 8's 0008.
    assert revisions["0008_labor_ingestion"] == "0007_invoice_supplier_ingestion"
    assert script.get_heads() == ["0008_labor_ingestion"]
    assert len(revisions) == 8  # 0001 .. 0008: Gate 7 added none


# --- read-only, no clock, no float ---------------------------------------------------------------


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_the_cost_code_writes_nothing(path: Path) -> None:
    names = identifiers(path)
    assert not names & WRITER_ATTRIBUTES, (path.name, names & WRITER_ATTRIBUTES)
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
            imported = {alias.name for alias in node.names}
            # a read-only module selects: it never imports a statement that writes or raw SQL
            assert not imported & (WRITER_IMPORTS - {"Session"}), (path.name, imported)
    # `session.add(...)` writes; `CALCULATION_CONTEXT.add(...)` is Decimal arithmetic
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr == "add":
            assert ast.unparse(node.value) == "CALCULATION_CONTEXT", (path.name, node.lineno)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_the_cost_code_reads_no_clock(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
            base = ast.unparse(node.value)
            assert base not in {"datetime", "date", "time", "datetime.datetime"}, (path.name, node)
        if isinstance(node, ast.ImportFrom) and node.module in {"time", "zoneinfo"}:
            pytest.fail(f"{path.name} imports {node.module}")
        if isinstance(node, ast.Import):
            assert not any(alias.name in {"time", "zoneinfo"} for alias in node.names), path.name


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_the_cost_code_uses_no_float(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        assert not (isinstance(node, ast.Name) and node.id == "float"), path.name
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name


def test_the_service_has_no_web_framework_dependency() -> None:
    code = (
        "import sys, app.modules.intelligence.costs.service; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "[]"


def test_only_the_standard_library_sqlalchemy_and_the_app_are_imported() -> None:
    allowed_roots = {"app", "sqlalchemy", "__future__"}
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


def test_the_cost_code_never_reads_staging_or_files() -> None:
    for path in SOURCES:
        names = identifiers(path)
        assert "InvoiceImportRow" not in names and "ImportFile" not in names, path.name
        assert "InvoiceMappingProfile" not in names, path.name


def test_only_the_canonical_invoice_tables_and_lead_time_zero_snapshots_are_read() -> None:
    read: set[str] = set()
    for path in SOURCES:
        read |= {n for n in identifiers(path) if n in {"Invoice", "InvoiceLine", "BookingSnapshot"}}
    assert read <= {"Invoice", "InvoiceLine", "BookingSnapshot"}
    assert {"Invoice", "InvoiceLine"} <= read


# --- no API, no worker, no dependency -------------------------------------------------------------


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])
    assert paths == ["/api/v1/health"]
    for word in ("cost", "cpor", "anomaly", "occupan", "decision", "evaluation"):
        assert not [p for p in paths if word in p]


def test_no_worker_task_and_no_scheduler_was_added() -> None:
    for word in ("cost", "cpor", "anomaly", "occupied", "evaluation"):
        assert not any(
            word in path.read_text(encoding="utf-8").lower() for path in WORKER_DIR.glob("*.py")
        ), word
    tasks = (WORKER_DIR / "tasks.py").read_text(encoding="utf-8")
    assert tasks.count("@app.task") == 1  # still only the Gate 0 heartbeat


def test_the_dependency_manifests_do_not_mention_scientific_ai_or_currency_libraries() -> None:
    for manifest in PYPROJECTS:
        text = manifest.read_text(encoding="utf-8").lower()
        for library in (
            "numpy",
            "pandas",
            "scipy",
            "scikit",
            "sklearn",
            "statsmodels",
            "openai",
            "anthropic",
            "langchain",
            "forex",
            "currencyconverter",
            "exchangerate",
            "babel",
            "pycountry",
        ):
            assert library not in text, (manifest.name, library)


# --- the documentation states the decisions -------------------------------------------------------


def test_the_documentation_records_the_gate_7_decisions() -> None:
    guide = " ".join((DOCS / "cost-cpor-anomaly-v1.md").read_text("utf-8").split())
    for phrase in (
        "COST_CPOR_ANOMALY",
        "cost-cpor-anomaly-v1",
        "cost-period-metric-v1",
        "cost-cpor-expected-v1",
        "operating proxy",
        "NOT a certified actual occupancy",
        "lead-time-0",
        "INVOICE_DATE_ATTRIBUTION",
        "A missing snapshot is not zero rooms",
        "never converts currencies",
        "OTHER is a data quality bucket",
        "classification coverage",
        "P75 + 1.5 * IQR",
        "relative materiality AND",
        "gross cost gap proxy",
        "MIN(baseline confidence, target quality)",
        "not persisted",
        "Known limits",
    ):
        assert phrase in guide, phrase
    adr = " ".join((DOCS / "adr" / "0013-cost-cpor-anomaly-v1.md").read_text("utf-8").split())
    for phrase in (
        "Calendar month",
        "Invoice-date attribution",
        "No accrual model",
        "Lead-time-0 denominator",
        "A missing snapshot is not zero",
        "Reconstructed clean occupancy",
        "70 % classification coverage",
        "OTHER is not actionable",
        "Same currency, no FX",
        "Seasonal window of +-2 months",
        "Median and IQR",
        "AND, not OR",
        "not a guaranteed saving",
        "The evaluation is not persisted",
    ):
        assert phrase in adr, phrase


def test_the_other_documents_mention_gate_7() -> None:
    architecture = (DOCS / "architecture-v1.md").read_text("utf-8")
    assert "Gate 7" in architecture and "cost-cpor-anomaly-v1" in architecture
    assert "cost-cpor-anomaly-v1" in (DOCS / "cost-ingestion-v1.md").read_text("utf-8")
    assert "cost-cpor-anomaly-v1" in (ROOT / "README.md").read_text("utf-8")
