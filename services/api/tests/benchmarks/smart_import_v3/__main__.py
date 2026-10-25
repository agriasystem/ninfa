"""python -m tests.benchmarks.smart_import_v3            (from services/api)

Builds the corpus, checks it against its own files, runs Smart Import V3 on every document
(deterministic: the optional assistant stays off), scores the answers against the hand-written
truth, and writes a console summary, a JSON file and a Markdown report.

Nothing is read from or written to a database, nothing leaves the process, no model is called.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from tests.benchmarks.smart_import_v3.corpus import build_corpus, manifest, validate
from tests.benchmarks.smart_import_v3.driver import evaluate
from tests.benchmarks.smart_import_v3.report import console_summary, markdown_report
from tests.benchmarks.smart_import_v3.runner import run_benchmark

REPO = Path(__file__).resolve().parents[5]
DEFAULT_JSON = REPO / "services/api/tests/benchmarks/results/smart-import-v3-benchmark-v1.json"
DEFAULT_MD = REPO / "docs/benchmarks/smart-import-v3-benchmark-v1.md"
MANIFEST = Path(__file__).with_name("manifest.json")


def write_text(path: Path, text: str) -> None:
    """UTF-8 with LF line ends on every platform (the repository normalises to LF)."""
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.benchmarks.smart_import_v3", description=__doc__
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="machine-readable results")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD, help="the written report")
    parser.add_argument(
        "--write-corpus", type=Path, help="also write every document to this directory"
    )
    parser.add_argument(
        "--write-manifest", action="store_true", help="refresh manifest.json (the truth)"
    )
    parser.add_argument(
        "--only", action="append", default=[], help="run only ids containing this text"
    )
    parser.add_argument(
        "--no-probes", action="store_true", help="skip the wrong-card and egress probes"
    )
    parser.add_argument("--no-memory", action="store_true", help="skip the tracemalloc pass")
    parser.add_argument("--repeats", type=int, default=3, help="timing repeats per document")
    parser.add_argument("--no-write", action="store_true", help="print only; write no file")
    args = parser.parse_args(argv)

    docs = build_corpus()
    problems = validate(docs)
    if problems:
        print("The corpus does not match its own truth (a bug of the benchmark):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    if args.only:
        docs = [d for d in docs if any(o in d.id for o in args.only)]
    if args.write_corpus:
        args.write_corpus.mkdir(parents=True, exist_ok=True)
        for doc in docs:
            (args.write_corpus / f"{doc.id}__{doc.filename}").write_bytes(doc.content)
        print(f"{len(docs)} documents written to {args.write_corpus}", file=sys.stderr)
    if args.write_manifest and not args.only:
        write_text(MANIFEST, json.dumps(manifest(docs), indent=1, ensure_ascii=False) + "\n")

    run = run_benchmark(
        docs, repeats=args.repeats, memory=not args.no_memory, probes=not args.no_probes
    )
    data = evaluate(run)
    print(console_summary(data))
    if args.no_write or args.only:
        return 0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    write_text(args.json, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    write_text(args.markdown, markdown_report(data, date.today().isoformat()))
    print(f"\nJSON      {args.json}\nMarkdown  {args.markdown}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
