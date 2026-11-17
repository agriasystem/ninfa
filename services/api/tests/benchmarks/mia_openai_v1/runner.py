"""python -m tests.benchmarks.mia_openai_v1            (from services/api)

Mia's evaluation. Two modes, one harness:

    --oracle   (default, offline) a scripted competent model plays every scenario through the REAL
               orchestrator, tools, worlds and scorer. It proves each rubric can be met and
               exercises
               every layer but the model on the whole corpus. No key, no network (it needs the TEST
               database, like the test suite).
    --live     the REAL model, through the adapter built exactly as production builds it. Opt-in:
               it needs a key, costs money and depends on a vendor. It never runs inside pytest.

Live is guarded: the worlds live in rolled-back transactions of the TEST database only (it refuses
to
run when TEST_DATABASE_URL is missing or equals DATABASE_URL), `--max-calls` is a HARD budget (a
call
over it never reaches the provider), `--cache-dir` makes a stopped run resumable without paying
twice
(the cache holds what a model said about SYNTHETIC hotels: keep it out of the repository), and
`--estimate-only` prices a run from the oracle's request sizes BEFORE any money is spent.

    exit 0  every gate met, every zero counter at 0
    exit 1  a quality gate failed
    exit 2  a zero counter is not 0 (a leak, an invented feature or figure, an injection obeyed, a
            write outside the person's own conversation, personal data sent)
    exit 3  NOT RUN: no OPENAI_API_KEY for --live. It is NOT a pass.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ai.gateway.tool_protocol import ToolCallingProvider
from tests.benchmarks.mia_openai_v1.corpus import all_scenarios, counts
from tests.benchmarks.mia_openai_v1.harness import ScenarioOutcome, run_all
from tests.benchmarks.mia_openai_v1.model import CATEGORY_MINIMUMS, Scenario
from tests.benchmarks.mia_openai_v1.providers import (
    CachingProvider,
    CountingProvider,
    OracleProvider,
    resolver_for,
)
from tests.benchmarks.mia_openai_v1.report import (
    Price,
    RunReport,
    markdown,
    parse_price,
    project,
    turn_stats,
)
from tests.benchmarks.mia_openai_v1.scoring import Aggregate, aggregate
from tests.benchmarks.mia_openai_v1.worlds import World, build_world
from tests.support import BookingFactory

DEFAULT_MODEL = "gpt-6.1-sol"
NOT_RUN = "MIA LIVE EVALUATION: NOT RUN - OPENAI_API_KEY NOT CONFIGURED"
HOW_TO_ENABLE = (
    "To run it: set OPENAI_API_KEY in the environment (never in a file that is committed), set "
    "TEST_DATABASE_URL, then `python -m tests.benchmarks.mia_openai_v1 --live --max-calls N "
    "--cache-dir DIR --price MODEL=IN:OUT` from services/api. Estimate first with --estimate-only."
)

OpenSession = Callable[[], AbstractContextManager[tuple[Session, BookingFactory]]]


# --- selection ------------------------------------------------------------------------------------


def _order(seed: int, scenario_id: str) -> str:
    return hashlib.sha1(f"{seed}:{scenario_id}".encode()).hexdigest()


def stratified_sample(scenarios: Sequence[Scenario], size: int, seed: int = 7) -> list[Scenario]:
    """`size` scenarios, spread over the categories in proportion to their size (at least one each
    while the size allows), chosen by a seeded hash: the same arguments give the same sample."""
    if size >= len(scenarios):
        return list(scenarios)
    groups: dict[str, list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        groups[scenario.category].append(scenario)
    total = len(scenarios)
    quota = {
        c: max(1 if size >= len(groups) else 0, size * len(g) // total) for c, g in groups.items()
    }
    remainders = sorted(groups, key=lambda c: (-(size * len(groups[c]) % total), c))
    while sum(quota.values()) < size:
        for category in remainders:
            if sum(quota.values()) >= size:
                break
            if quota[category] < len(groups[category]):
                quota[category] += 1
    while sum(quota.values()) > size:
        biggest = max(quota, key=lambda c: (quota[c], c))
        quota[biggest] -= 1
    chosen: set[str] = set()
    for category, group in groups.items():
        ranked = sorted(group, key=lambda s: _order(seed, s.id))
        chosen.update(s.id for s in ranked[: quota[category]])
    return [s for s in scenarios if s.id in chosen]


def select(
    scenarios: Sequence[Scenario],
    *,
    only: str | None = None,
    ids: Sequence[str] = (),
    sample: int | None = None,
    seed: int = 7,
) -> list[Scenario]:
    chosen = list(scenarios)
    if only:
        chosen = [s for s in chosen if s.category == only]
    if ids:
        wanted = set(ids)
        chosen = [s for s in chosen if s.id in wanted]
    if sample is not None:
        chosen = stratified_sample(chosen, sample, seed)
    return chosen


# --- executing ------------------------------------------------------------------------------------


def execute(
    scenarios: Sequence[Scenario],
    session: Session,
    factory: BookingFactory,
    *,
    mode: str,
    model: str,
    provider: ToolCallingProvider | None = None,
    price: Price | None = None,
    max_calls: int | None = None,
    cache_dir: Path | None = None,
    stop: Callable[[], bool] | None = None,
) -> RunReport:
    """Runs `scenarios` against worlds built in `session` (the caller rolls it back)."""
    worlds: dict[str, World] = {}

    def get_world(name: str) -> World:
        if name not in worlds:
            worlds[name] = build_world(name, factory, session)
        return worlds[name]

    counting: CountingProvider | None = None
    caching: CachingProvider | None = None
    if mode == "oracle":

        def provider_for(scenario: Scenario, index: int, turn: Any, world: World) -> Any:
            return OracleProvider(turn.oracle, world.truth, resolver_for(world))

    else:
        assert provider is not None
        inner: ToolCallingProvider = provider
        if cache_dir is not None:
            caching = CachingProvider(inner, cache_dir, model)
            inner = caching
        counting = CountingProvider(inner, max_calls)
        shared = counting

        def provider_for(scenario: Scenario, index: int, turn: Any, world: World) -> Any:
            return shared

    def should_stop() -> bool:
        return (counting is not None and counting.exhausted) or (stop is not None and stop())

    outcomes = run_all(scenarios, get_world, provider_for, stop=should_stop)
    return build_report(
        outcomes,
        mode=mode,
        model=model,
        price=price,
        selected=len(scenarios),
        counting=counting,
        caching=caching,
    )


def build_report(
    outcomes: list[ScenarioOutcome],
    *,
    mode: str,
    model: str,
    price: Price | None,
    selected: int,
    counting: CountingProvider | None = None,
    caching: CachingProvider | None = None,
) -> RunReport:
    scored = [
        (
            outcome.scenario,
            turn.score,
            turn.run.rubric.follow_up,
            turn.run.result.status.value == "UNAVAILABLE",
        )
        for outcome in outcomes
        for turn in outcome.turns
    ]
    aggregated: Aggregate = aggregate(scored)
    aggregated.corrected = sum(1 for o in outcomes for t in o.turns if t.metrics.corrected)
    report = RunReport(
        mode=mode,
        model=model,
        aggregate=aggregated,
        outcomes=outcomes,
        rows=turn_stats(outcomes),
        price=price,
        scenarios_run=len(outcomes),
        scenarios_selected=selected,
        calls_made=0 if counting is None else counting.calls,
        calls_cached=0 if caching is None else caching.hits,
        budget_exhausted=counting is not None and counting.exhausted,
    )
    if counting is not None and counting.refused:
        report.notes.append(f"{counting.refused} call(s) refused by the budget and never sent.")
    return report


# --- the database and the key ---------------------------------------------------------------------


def _dotenv_value(name: str) -> str | None:
    from dotenv import dotenv_values

    root = Path(__file__).resolve().parents[5]
    value = dotenv_values(root / ".env").get(name)
    return value or None


def test_database_url(environ: Mapping[str, str]) -> str | None:
    return environ.get("TEST_DATABASE_URL") or _dotenv_value("TEST_DATABASE_URL")


def dev_database_url(environ: Mapping[str, str]) -> str | None:
    return environ.get("DATABASE_URL") or _dotenv_value("DATABASE_URL")


class RefusedDatabaseError(Exception):
    """The run was asked to use a database it must never touch."""


def checked_test_database(environ: Mapping[str, str]) -> str:
    url = test_database_url(environ)
    if not url:
        raise RefusedDatabaseError(
            "TEST_DATABASE_URL is not set: the evaluation never uses another one"
        )
    if url == dev_database_url(environ):
        raise RefusedDatabaseError("TEST_DATABASE_URL equals DATABASE_URL: refusing to touch it")
    return url


@contextmanager
def rolled_back_session(url: str) -> Iterator[tuple[Session, BookingFactory]]:
    """A session on the TEST database inside a transaction that is always rolled back."""
    from alembic import command

    from app.db.session import create_db_engine
    from tests.support import alembic_config

    command.upgrade(alembic_config(url), "head")
    engine = create_db_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session, BookingFactory(session)
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _key(environ: Mapping[str, str]) -> str:
    key = environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    from tests.live_openai_acceptance import _key_of_the_application

    return _key_of_the_application()


def _live_provider(key: str, model: str, database_url: str) -> ToolCallingProvider:
    """Mia's provider exactly as production builds it (`build_mia_provider`)."""
    from app.core.config import Settings
    from app.modules.ai.gateway.factory import build_mia_provider

    settings = Settings(
        mia_provider="openai",
        openai_api_key=key,
        mia_openai_model=model,
        database_url=database_url,
    )
    return build_mia_provider(settings)


# --- the command line -----------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tests.benchmarks.mia_openai_v1")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--oracle", action="store_true", help="offline run with the scripted oracle (default)"
    )
    mode.add_argument("--live", action="store_true", help="REAL model, opt-in, needs a key")
    mode.add_argument(
        "--estimate-only", action="store_true", help="price a live run from the oracle"
    )
    mode.add_argument("--list", action="store_true", help="print the corpus counts and stop")
    p.add_argument(
        "--sample", type=int, default=None, help="a seeded stratified sample of N scenarios"
    )
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--only", default=None, choices=sorted(CATEGORY_MINIMUMS))
    p.add_argument("--ids", default="", help="comma separated scenario ids")
    p.add_argument("--max-calls", type=int, default=None, help="HARD cap of calls to the provider")
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="resumable live cache (keep it OUT of the repository)",
    )
    p.add_argument(
        "--price",
        action="append",
        default=[],
        metavar="MODEL=IN:OUT",
        help="dollars per million tokens",
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--json", dest="json_out", type=Path, default=None)
    p.add_argument("--markdown", dest="markdown_out", type=Path, default=None)
    p.add_argument(
        "--show-text",
        action="store_true",
        help="print texts of failing turns (may hold model output)",
    )
    p.add_argument(
        "--assume-output-tokens",
        type=int,
        default=700,
        help="output tokens per model call for --estimate-only",
    )
    return p


def _price_for(model: str, specs: Sequence[str]) -> Price | None:
    for spec in specs:
        price = parse_price(spec)
        if price.model == model:
            return price
    return None


def _write(report: RunReport, args: argparse.Namespace) -> None:
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown(report, show_text=args.show_text), encoding="utf-8")


def console(report: RunReport) -> str:
    agg = report.aggregate
    lines = [
        f"Mia evaluation ({report.mode}, {report.model}): {report.scenarios_run}/"
        f"{report.scenarios_selected} scenarios, {agg.turns} turns",
        "zero counters: " + (", ".join(f"{k}={v}" for k, v in agg.tripped.items()) or "all 0"),
    ]
    for name, count in agg.gaps.items():
        lines.append(f"known gap {name}: {count}")
    for metric in sorted(report.aggregate.rates):
        rate = agg.rate(metric)
        if rate is not None:
            lines.append(f"  {metric}: {100 * rate:.1f}%")
    failures = agg.gate_failures()
    lines.append("gates: " + ("all met" if not failures else f"BELOW BAR: {sorted(failures)}"))
    lines.append(f"exit code {report.exit_code}")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    open_session: OpenSession | None = None,
    live_provider: Callable[[str, str, str], ToolCallingProvider] = _live_provider,
) -> int:
    args = parser().parse_args(argv)
    env = os.environ if environ is None else environ
    ids = [i for i in args.ids.split(",") if i]
    scenarios = select(all_scenarios(), only=args.only, ids=ids, sample=args.sample, seed=args.seed)

    if args.list:
        for category, minimum in CATEGORY_MINIMUMS.items():
            print(f"{category}: {counts()[category]} (minimum {minimum})")
        print(f"total: {sum(counts().values())}")
        return 0

    price = _price_for(args.model, args.price)
    if args.live:
        key = _key(env)
        if not key:
            print(NOT_RUN)
            print(HOW_TO_ENABLE)
            return 3
        try:
            url = checked_test_database(env)
        except RefusedDatabaseError as refusal:
            print(f"REFUSED: {refusal}")
            return 4
        provider: ToolCallingProvider | None = live_provider(key, args.model, url)
        mode = "live"
    else:
        try:
            url = checked_test_database(env) if open_session is None else ""
        except RefusedDatabaseError as refusal:
            print(f"REFUSED: {refusal}")
            return 4
        provider = None
        mode = "oracle"

    opener: OpenSession = open_session or (lambda: rolled_back_session(url))
    with opener() as (session, factory):
        report = execute(
            scenarios,
            session,
            factory,
            mode=mode,
            model=args.model if mode == "live" else "oracle (scripted)",
            provider=provider,
            price=price,
            max_calls=args.max_calls,
            cache_dir=args.cache_dir,
        )

    if args.estimate_only:
        everything = sum(len(scenario.turns) for scenario in all_scenarios())
        estimate = {
            "selected": project(
                report.rows, sum(1 for _ in report.rows), price, args.assume_output_tokens
            ),
            "full_corpus": project(report.rows, everything, price, args.assume_output_tokens),
            "basis": "request sizes of the oracle's own calls (characters / 3.2 per token) and "
            f"{args.assume_output_tokens} assumed output tokens per model call; the real model may "
            "make more or fewer calls and think more or less",
        }
        print(json.dumps(estimate, indent=1))
        return 0

    _write(report, args)
    print(console(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
