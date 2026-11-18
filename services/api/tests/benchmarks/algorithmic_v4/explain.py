"""python -m tests.benchmarks.algorithmic_v4.explain [--ids ...]   (from services/api)

WHY V4 read a document the way it did, header by header:

    header -> what V3's word rules and names said -> what V4's vocabulary said -> what the values
    proved or ruled out -> what the relations added -> the total -> the field chosen, how firm,
    how sure -> what the domain validation said.

It prints counts, shapes and phrases of the VOCABULARY only - never a value of the file - so it is
safe to paste into a report. With no `--ids` it explains the three headers of the brief
(`reservation_code`, `booking_status`, `room_total`) in the first problem-corpus document that has
them.
"""

import argparse
from collections.abc import Sequence

from app.modules.data_sources.algorithmic.engine import DEFAULT, AlgorithmicEngine, Trace
from app.modules.data_sources.algorithmic.selector import use_engine, use_engine_instance
from app.modules.data_sources.semantics import name_candidates
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.algorithmic_v4.problem_corpus import build_problem_corpus
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.smart_import_v3.observe import make_service, run

SEM = {
    "bookings": BOOKINGS,
    "labor": LABOR,
    "costs": COSTS,
}
DOMAIN = {
    "bookings": DataSourceDomain.BOOKINGS,
    "labor": DataSourceDomain.LABOR,
    "costs": DataSourceDomain.COSTS,
}


def v3_candidates(card: str, header: str) -> str:
    found = name_candidates(SEM[card], header)
    if not found:
        return "nothing"
    return ", ".join(f"{c.field} {c.name.value} {c.score:.2f}" for c in found[:3])


def explain(doc: Doc, headers: Sequence[str] | None = None) -> list[str]:
    """The explanation of one document as Markdown lines."""
    lines = [f"### {doc.id} ({doc.card}, {doc.filename})", ""]
    seen: list[Trace] = []
    engine = AlgorithmicEngine(DEFAULT, on_trace=seen.append)
    with use_engine("v3"):
        before = run(make_service(), doc.card, doc.filename, doc.content)
    with use_engine_instance(engine):
        after = run(make_service(), doc.card, doc.filename, doc.content)
    # the trace of the card's own kind of data is the last one the understanding produced for it
    trace = seen[-1] if seen else Trace()
    v3 = {c.header: c for c in before.columns}
    lines += [
        f"V3: level **{before.level}**, questions {[q.kind for q in before.questions] or 'none'}",
        f"V4: level **{after.level}**, questions {[q.kind for q in after.questions] or 'none'}",
        "",
        "| header | V3 reads | V4 candidates (total = header x values + relation) | V4 selected "
        "| validation |",
        "|---|---|---|---|---|",
    ]
    for column in after.columns:
        if headers and column.header not in headers:
            continue
        mine = [s for s in trace.scores if s.column == column.position]
        weighed = "<br>".join(
            f"`{s.field}` {s.total:.2f} (header {s.header:.2f} {s.header_kind}"
            + (f" '{s.phrase}'" if s.phrase else "")
            + f", values {'-' if s.values is None else f'{s.values:.2f}'}"
            + (f", proof {s.proof:.2f}" if s.proof else "")
            + (f", relation +{s.relational:.2f}" if s.relational else "")
            + (f", RULED OUT: {s.veto}" if s.veto else "")
            + ")"
            for s in sorted(mine, key=lambda s: -s.total)[:3]
        )
        picked = trace.selected.get(column.position)
        selected = (
            f"`{picked[0]}` margin {picked[1]:.2f}, {picked[2].value}" if picked else "nothing"
        )
        was = v3[column.header]
        validation = "-"
        lines.append(
            f"| `{column.header}` | {v3_candidates(doc.card, column.header)} -> "
            f"`{was.field or '-'}` {was.level or ''} | {weighed or 'no candidate'} | "
            f"{selected} -> final `{column.field or '-'}` {column.level or ''} | {validation} |"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.benchmarks.algorithmic_v4.explain")
    parser.add_argument(
        "--ids", nargs="*", default=["PB_snake_xlsx", "PB_camel_xlsx", "PB_glued_xlsx"]
    )
    parser.add_argument("--headers", nargs="*", default=None)
    args = parser.parse_args(argv)
    docs = {d.id: d for d in build_problem_corpus()}
    for doc_id in args.ids:
        print("\n".join(explain(docs[doc_id], args.headers)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
