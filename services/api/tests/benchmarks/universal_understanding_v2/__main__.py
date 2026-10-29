"""python -m tests.benchmarks.universal_understanding_v2            (from services/api)

Builds the unseen corpus, checks it against its own files, runs Smart Import V3 on every document
as a FIRST upload (no learned profile; deterministic: the optional assistant stays off), scores the
answers against the hand-written truth, and writes a console summary, a JSON file and a Markdown
report.

Nothing is read from or written to a database, nothing leaves the process, no model is called.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from tests.benchmarks.smart_import_v3.runner import run_benchmark
from tests.benchmarks.universal_understanding_v2.corpus import (
    GROUPS,
    build_corpus,
    manifest,
    split_of,
    validate,
)
from tests.benchmarks.universal_understanding_v2.evaluate import evaluate
from tests.benchmarks.universal_understanding_v2.report import console_summary, markdown_report
from tests.benchmarks.universal_understanding_v2.stages import measure

REPO = Path(__file__).resolve().parents[5]
DEFAULT_JSON = REPO / "services/api/tests/benchmarks/results/universal-understanding-v2.json"
DEFAULT_MD = REPO / "docs/benchmarks/smart-import-v3-universal-understanding-2.md"
MANIFEST = Path(__file__).with_name("manifest.json")


def write_text(path: Path, text: str) -> None:
    """UTF-8 with LF line ends on every platform (the repository normalises to LF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.benchmarks.universal_understanding_v2", description=__doc__
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="machine-readable results")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD, help="the written report")
    parser.add_argument("--title", help="title of the Markdown report")
    parser.add_argument(
        "--groups", nargs="+", choices=sorted(GROUPS), help="run only these groups of documents"
    )
    parser.add_argument("--only", action="append", default=[], help="ids containing this text")
    parser.add_argument(
        "--split",
        choices=("dev", "holdout", "all"),
        default="all",
        help="dev: the documents whose failures are studied; holdout: the ones kept unseen",
    )
    parser.add_argument("--write-corpus", type=Path, help="also write every document here")
    parser.add_argument("--write-manifest", action="store_true", help="refresh manifest.json")
    parser.add_argument("--no-probes", action="store_true", help="skip wrong-card and egress")
    parser.add_argument("--no-stages", action="store_true", help="skip the per-stage timing")
    parser.add_argument("--repeats", type=int, default=3, help="timing repeats per document")
    parser.add_argument("--no-write", action="store_true", help="print only; write no file")
    args = parser.parse_args(argv)

    docs = build_corpus(tuple(args.groups) if args.groups else None)
    problems = validate(docs)
    if problems:
        print("The corpus does not match its own truth (a bug of the benchmark):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    if args.split != "all":
        docs = [d for d in docs if split_of(d) == args.split]
    if args.only:
        docs = [d for d in docs if any(o in d.id for o in args.only)]
    if args.write_corpus:
        args.write_corpus.mkdir(parents=True, exist_ok=True)
        for doc in docs:
            (args.write_corpus / f"{doc.id}__{doc.filename}").write_bytes(doc.content)
        print(f"{len(docs)} documents written to {args.write_corpus}", file=sys.stderr)
    if args.write_manifest and not args.only and not args.groups:
        write_text(MANIFEST, json.dumps(manifest(docs), indent=1, ensure_ascii=False) + "\n")

    run = run_benchmark(docs, repeats=args.repeats, memory=False, probes=not args.no_probes)
    stages = None if args.no_stages else measure(docs, repeats=args.repeats)
    data = evaluate(run, stages)
    print(console_summary(data))
    if args.no_write or args.only:
        return 0
    write_text(args.json, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    write_text(args.markdown, markdown_report(data, date.today().isoformat(), args.title))
    print(f"\nJSON      {args.json}\nMarkdown  {args.markdown}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
