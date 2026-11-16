"""python -m tests.benchmarks.source_learning.ai_calls            (from services/api)

How many times is a model asked about a source a person has ALREADY confirmed?

The 12 families of the Source Learning benchmark, in their 8 versions: the first file teaches the
source (the person decides, the import remembers it), then next month, columns moved, a junk
column, cosmetic headers, a new column, a column gone, a column that changed meaning. A counting
stand-in for the model reads every column right; only how often it is ASKED is measured. Twice:
as V1.1 asks, and as V1 asked (`legacy_gate`).

It uses the TEST database inside a transaction that is rolled back, like the Source Learning
benchmark itself. No key, no network, no money.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode
from app.modules.data_sources.service import DataSourcesService
from tests.benchmarks.source_learning.families import FAMILIES, Expect, Family, versions
from tests.benchmarks.source_learning.runner import Bench
from tests.semantic_support import Behaviour, SemanticStandIn

REPO = Path(__file__).resolve().parents[5]
TRUSTED = tuple(f for f in FAMILIES if not f.control)
# Versions of the SAME source that Source Learning recognises: nothing is asked again of anybody
RECOGNISED = {Expect.EXACT, Expect.COMPATIBLE}


def counted(session: Session, family: Family) -> tuple[Bench, SemanticStandIn]:
    """A bench whose service has a model that reads right every column the family can ever hold,
    and counts how often it is asked. Production's configuration: the certainty withdrawn."""
    truth: dict[str, str] = {}
    for version in versions(family):
        truth.update(version.truth)
    model = SemanticStandIn(Behaviour.ORACLE, truth)
    bench = Bench(session, lambda _message: None, workspace=f"ws-{family.id.lower()}")
    bench.service = DataSourcesService(
        session,
        TenantContext(bench.workspace.id),
        resolver=ImportUnderstandingResolver(
            model, AiMode.ASSIST, corroborate=True, vocabulary_certainty=False
        ),
    )
    return bench, model


def calls_per_version(
    session: Session, family: Family
) -> tuple[int, dict[str, tuple[Expect, int, int]]]:
    """(calls the first time, then for each later version: what it is, calls on the property that
    taught the source, calls on one that knows nothing)."""
    bench, model = counted(session, family)
    plan = versions(family)
    taught_in = bench.factory.property(bench.workspace)
    cold_in = bench.factory.property(bench.workspace)
    bench.teach(taught_in.id, family, plan[0])
    first = model.calls
    out: dict[str, tuple[Expect, int, int]] = {}
    for version in plan[1:]:
        before = model.calls
        bench.understand(taught_in.id, family, version)
        learned = model.calls - before
        before = model.calls
        bench.understand(cold_in.id, family, version)
        out[version.key] = (version.expect, learned, model.calls - before)
    return first, out


def measure(session: Session) -> dict[str, Any]:
    first_time = learned = cold = recognised_versions = recognised_asked = 0
    for family in TRUSTED:
        first, calls = calls_per_version(session, family)
        first_time += first
        for expect, with_memory, without in calls.values():
            learned += with_memory
            cold += without
            if expect in RECOGNISED:
                recognised_versions += 1
                recognised_asked += 1 if with_memory else 0
    return {
        "families": len(TRUSTED),
        "versions_after_the_first": 7 * len(TRUSTED),
        "calls_the_first_time_a_source_arrives": first_time,
        "calls_on_later_files_of_a_source_that_was_confirmed": learned,
        "calls_on_the_same_files_of_a_source_nobody_confirmed": cold,
        "calls_avoided_by_remembering": cold - learned,
        "recognised_versions": recognised_versions,
        "recognised_versions_that_asked_the_model": recognised_asked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.source_learning.ai_calls")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(REPO / ".env").get(
        "TEST_DATABASE_URL"
    )
    if not url:
        raise SystemExit("TEST_DATABASE_URL is not set (see .env.example)")
    os.environ.update(
        {
            "APP_ENV": "test",
            "DEBUG": "false",
            "DATABASE_URL": url,
            "IMPORT_UNDERSTANDING_MODE": "off",
        }
    )
    from alembic import command

    from app.db.session import create_db_engine
    from tests.benchmarks.smart_import_v3.assist_efficiency import legacy_gate
    from tests.support import alembic_config

    command.upgrade(alembic_config(url), "head")
    engine = create_db_engine(url)
    results: dict[str, Any] = {}
    for label, gated in (("V1.1", False), ("V1", True)):
        connection = engine.connect()
        transaction = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            if gated:
                with legacy_gate():
                    results[label] = measure(session)
            else:
                results[label] = measure(session)
        finally:
            session.close()
            transaction.rollback()  # nothing of the benchmark stays in the database
            connection.close()
        print(f"{label}: {results[label]}", file=sys.stderr, flush=True)
    engine.dispose()
    text = json.dumps(results, indent=1, sort_keys=True)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
