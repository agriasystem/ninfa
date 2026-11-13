"""The safety of what an import MEANS, re-run with the semantic layer doing real work.

FULL / PARTIAL / DELTA, the identical import that moves nothing, a same-day revision, an absence
that removes nothing, a remembered FULL that is confirmed again before it takes anything away: all
of that was approved, and none of it may depend on whether a model read a column. So the existing
suites of those rules are run again, test by test, with ONE difference: the bookings file calls its
status column "Condizione" - a word NINFA's rules do not know, so without the layer the file is not
even READY - and the app has the layer in ASSIST mode with a model that reads that column right.

Nothing here is rewritten: the very test functions of `test_import_scope_bookings` and
`test_remembered_scope_bookings` run (through the real API and the real database, rolled back), and
what they assert about scope, removal, revision and confirmation must still hold. The first test of
this module proves the runs are not vacuous: without the layer the file would not get past READY.
"""
# ruff: noqa: F401, F811 - the suites are imported to be run, the fixtures to be found

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode
from tests import test_import_scope_bookings as scope
from tests import test_remembered_scope_bookings as remembered
from tests.data_sources_support import SourcesEnv
from tests.semantic_support import Behaviour, SemanticStandIn
from tests.smart_import_support import understand
from tests.test_import_scope_bookings import env  # the fixture both suites use
from tests.test_remembered_scope_bookings import complete_source  # a fixture of the second one

_UNKNOWN_TO_THE_RULES = "Condizione"


def _renamed(headers: list[str]) -> list[str]:
    return [_UNKNOWN_TO_THE_RULES if header == "Stato" else header for header in headers]


@pytest.fixture(autouse=True)
def the_model_reads_the_status_column(
    monkeypatch: pytest.MonkeyPatch, api_client: TestClient
) -> Iterator[SemanticStandIn]:
    monkeypatch.setattr(scope, "HEADERS", _renamed(scope.HEADERS))
    monkeypatch.setattr(remembered, "HEADERS", _renamed(remembered.HEADERS))
    provider = SemanticStandIn(Behaviour.ORACLE, {_UNKNOWN_TO_THE_RULES: "status"})
    cast(FastAPI, api_client.app).state.import_understanding_resolver = ImportUnderstandingResolver(
        provider, AiMode.ASSIST, corroborate=True
    )
    yield provider


def test_these_runs_are_real_the_model_reads_a_column_the_rules_do_not(
    api_client: TestClient,
    env: SourcesEnv,
    the_model_reads_the_status_column: SemanticStandIn,
) -> None:
    content = scope.file_of(*scope.ONE_TWO_THREE)

    with_the_layer = understand(api_client, env, scope.BOOKINGS, "a.xlsx", content)
    cast(FastAPI, api_client.app).state.import_understanding_resolver = ImportUnderstandingResolver(
        None
    )
    without_it = understand(api_client, env, scope.BOOKINGS, "a.xlsx", content)

    assert with_the_layer["understanding"]["level"] == "READY"
    assert the_model_reads_the_status_column.calls >= 1
    assert without_it["understanding"]["level"] == "MANUAL"
    assert [b["code"] for b in without_it["understanding"]["blockers"]] == ["MISSING_REQUIRED"]


def _suites(*modules: object) -> dict[str, Callable[..., None]]:
    found: dict[str, Callable[..., None]] = {}
    for tag, module in zip(("scope", "remembered"), modules, strict=True):
        for name, value in vars(module).items():
            if name.startswith("test_") and callable(value):
                found[f"test_{tag}_{name.removeprefix('test_')}"] = value
    return found


# every test of both suites, under its own name, run with the layer on
globals().update(_suites(scope, remembered))
