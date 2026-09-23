"""The Priority Engine is read-only and needs no database at all (spec part T)."""

import ast
import inspect
from datetime import date
from pathlib import Path

import app.modules.intelligence.priority as priority_package
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from tests.priority_support import DEFAULT_PROPERTY_ID, DEFAULT_WORKSPACE_ID, pickup_evaluation

_CONTEXT = PriorityContext(DEFAULT_WORKSPACE_ID, DEFAULT_PROPERTY_ID, date(2026, 9, 1))


def test_priorityservice_needs_no_session_or_tenant_context_to_construct() -> None:
    # PriorityService defines no __init__ of its own (there is nothing to store): introspecting
    # the inherited object.__init__ only shows the generic *args/**kwargs, never a session param.
    parameters = set(inspect.signature(PriorityService.__init__).parameters)
    assert not {"session", "tenant_context", "tenant", "engine", "connection"} & parameters
    PriorityService()  # constructs with zero arguments


def test_rank_takes_no_session_argument() -> None:
    parameters = inspect.signature(PriorityService.rank).parameters
    assert set(parameters) == {"self", "context", "evaluations"}


def test_zero_sql_zero_orm_import_anywhere_in_the_priority_package() -> None:
    package_dir = Path(priority_package.__file__).parent
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            assert "sqlalchemy" not in names, f"{source.name} imports sqlalchemy"


def test_source_evaluations_are_never_mutated_by_ranking() -> None:
    evaluation = pickup_evaluation()
    facts_before = evaluation.facts
    fingerprint_before = evaluation.calculation_fingerprint
    PriorityService().rank(_CONTEXT, [evaluation])
    # frozen dataclasses cannot be mutated in place; this asserts the SAME object is still intact.
    assert evaluation.facts is facts_before
    assert evaluation.calculation_fingerprint == fingerprint_before


def test_no_write_commit_flush_or_session_call_anywhere_in_the_priority_package() -> None:
    # "add" is deliberately excluded: `CALCULATION_CONTEXT.add(...)` is legitimate Decimal
    # arithmetic (see impact.py/scoring.py), not a session write, so it would false-positive here.
    package_dir = Path(priority_package.__file__).parent
    forbidden = {"commit", "rollback", "flush", "execute", "merge"}
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        calls = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in forbidden
        ]
        assert calls == [], f"{source.name} calls forbidden write method(s): {calls}"
