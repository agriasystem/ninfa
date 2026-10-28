"""python -m tests.benchmarks.source_learning            (from services/api)

Source Learning Benchmark V1: 13 sources (11 the person has to teach, 2 the engine reads alone) in
8 versions each = 104 documents, understood with and without a memory of what a person confirmed;
and its multi-source extension: 3 properties with 4 recurring families each in ONE kind of data, a
timeline of files that comes and goes between them.

It uses the TEST database (`TEST_DATABASE_URL`), inside a transaction that is rolled back: nothing
is left behind, and the development database is never touched. No model, no embedding, no external
service: `IMPORT_UNDERSTANDING_MODE` is off.

    --json / --markdown   where to write the result (default: the versioned files)
    --only L1             only the families whose id contains this (no multi-source part)
    --no-write            print the summary only
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[5]
DEFAULT_JSON = REPO / "services/api/tests/benchmarks/results/source-learning-benchmark-v1.json"
DEFAULT_MD = REPO / "docs/benchmarks/source-learning-benchmark-v1.md"


def _database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(REPO / ".env").get(
        "TEST_DATABASE_URL"
    )
    if not url:
        raise SystemExit(
            "TEST_DATABASE_URL is not set: configure it in .env (see .env.example) and create the "
            "test database (docs/development/local-development.md)."
        )
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.source_learning")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    # The test environment, as the suite prepares it: never the development database, no assistant.
    url = _database_url()
    os.environ.update(
        {
            "APP_ENV": "test",
            "DEBUG": "false",
            "DATABASE_URL": url,
            "IMPORT_UNDERSTANDING_MODE": "off",
        }
    )
    from alembic import command
    from sqlalchemy.orm import Session

    from app.db.session import create_db_engine
    from tests.benchmarks.source_learning.families import FAMILIES
    from tests.benchmarks.source_learning.multi import SITES, run_multi_family
    from tests.benchmarks.source_learning.report import markdown
    from tests.benchmarks.source_learning.runner import run_benchmark
    from tests.support import alembic_config

    families = tuple(f for f in FAMILIES if not args.only or any(o in f.id for o in args.only))
    command.upgrade(alembic_config(url), "head")
    engine = create_db_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        data = run_benchmark(
            session,
            families,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        if not args.only:
            data["multi_family"] = run_multi_family(
                session,
                SITES,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
    finally:
        session.close()
        transaction.rollback()  # nothing of the benchmark stays in the database
        connection.close()
        engine.dispose()

    summary = {k: v for k, v in data.items() if k not in {"versions", "per_family", "multi_family"}}
    if "multi_family" in data:
        summary["multi_family"] = {
            k: v for k, v in data["multi_family"].items() if k not in {"steps", "per_site"}
        }
    print(json.dumps(summary, indent=1, default=str))
    failed = bool(data["failures"]) or bool(data.get("multi_family", {}).get("failures"))
    official = args.json == DEFAULT_JSON and args.markdown == DEFAULT_MD
    if args.no_write or (args.only and official):
        return 1 if failed else 0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        markdown(data, date.today().isoformat()), encoding="utf-8", newline="\n"
    )
    print(f"JSON {args.json}\nMarkdown {args.markdown}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
