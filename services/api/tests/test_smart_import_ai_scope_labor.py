"""The same re-run for staff files: absence, partial files, a remembered FULL, with a model.

Where `test_smart_import_ai_scope` re-runs the bookings suites with the status column read by the
semantic layer, this re-runs the staff suites with the DEPARTMENT column read by it: the file
calls it "Postazione", a word NINFA's rules do not know. Only a day-and-department plan that a FULL
file no longer holds may be removed, 0 hours is not a removal, a PARTIAL or DELTA file removes
nothing and a remembered FULL is confirmed again before it takes anything away - the very test
functions that assert it run, unchanged, with the model in the loop.
"""
# ruff: noqa: F401, F811 - the suites are imported to be run, the fixtures to be found

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode
from tests import test_import_scope_labor as scope
from tests import test_labor_partial_absence as partial
from tests import test_remembered_scope_labor as remembered
from tests.semantic_support import Behaviour, SemanticStandIn

_UNKNOWN_TO_THE_RULES = "Postazione"


def _renamed(headers: list[str]) -> list[str]:
    return [_UNKNOWN_TO_THE_RULES if header == "Reparto" else header for header in headers]


@pytest.fixture(autouse=True)
def the_model_reads_the_department_column(
    monkeypatch: pytest.MonkeyPatch, api_client: TestClient
) -> Iterator[SemanticStandIn]:
    monkeypatch.setattr(scope, "STAFF_HEADERS", _renamed(scope.STAFF_HEADERS))
    monkeypatch.setattr(partial, "HEADERS", _renamed(partial.HEADERS))
    monkeypatch.setattr(remembered, "HEADERS", _renamed(remembered.HEADERS))
    provider = SemanticStandIn(Behaviour.ORACLE, {_UNKNOWN_TO_THE_RULES: "role"})
    # The scope rules are run against the STRONGEST configuration the layer ever had - a model's
    # reading accepted as certain (the withdrawn vocabulary certainty, ADR 0052): if FULL /
    # PARTIAL / DELTA are not decided by the model even then, a model held to a question cannot
    # decide them
    # either. It is switched on HERE, explicitly; no default turns it on.
    cast(FastAPI, api_client.app).state.import_understanding_resolver = ImportUnderstandingResolver(
        provider, AiMode.ASSIST, corroborate=True, vocabulary_certainty=True
    )
    yield provider


def _suites() -> dict[str, object]:
    found: dict[str, object] = {}
    for tag, module in (("scope", scope), ("partial", partial), ("remembered", remembered)):
        for name, value in vars(module).items():
            if name.startswith("test_") and callable(value):
                found[f"test_{tag}_{name.removeprefix('test_')}"] = value
            elif getattr(value, "_pytestfixturefunction", None) is not None or hasattr(
                value, "_fixture_function_marker"
            ):
                found.setdefault(name, value)  # the fixtures those suites bring with them
    return found


globals().update(_suites())
