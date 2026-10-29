"""The Universal Understanding Benchmark V2 as a whole: assembled, checked against its own files,
summarised, hashed.

It is a corpus of files NO ONE has tuned Smart Import on: generated from recipes (never the 240
documents of the official benchmark), with the truth written next to each file. It never replaces
the official corpus; it is read beside it.

Groups (the difficulty is in the document id and its tags):
  positives   bookings / labor / costs, EASY / MEDIUM / HARD / ADVERSARIAL
  negatives   office spreadsheets that are none of the three (a refusal is the right answer)
  unsupported files that are not a readable .csv / .xlsx (a clean refusal is the right answer)
"""

import hashlib
from collections import Counter
from importlib import import_module
from typing import Any

from tests.benchmarks.smart_import_v3.corpus import manifest
from tests.benchmarks.smart_import_v3.corpus import validate as validate_documents
from tests.benchmarks.smart_import_v3.model import Doc
from tests.benchmarks.universal_understanding_v2.common import DIFFICULTIES, difficulty_of

PACKAGE = "tests.benchmarks.universal_understanding_v2"
DOMAINS = ("bookings", "labor", "costs")
DOMAIN_NAMES = {"bookings": "Prenotazioni", "labor": "Personale", "costs": "Costi"}
# group -> (module, function); a group is only imported when it is asked for
GROUPS: dict[str, tuple[str, str]] = {
    "bookings": ("gen_bookings", "build"),
    "labor": ("gen_labor", "build"),
    "costs": ("gen_costs", "build"),
    "negative": ("gen_negative", "build_negative"),
    "unsupported": ("gen_negative", "build_unsupported"),
}


def build_corpus(groups: tuple[str, ...] | None = None) -> list[Doc]:
    docs: list[Doc] = []
    for name, (module, function) in GROUPS.items():
        if groups is None or name in groups:
            docs.extend(getattr(import_module(f"{PACKAGE}.{module}"), function)())
    ids = Counter(d.id for d in docs)
    duplicated = [i for i, n in ids.items() if n > 1]
    if duplicated:
        raise ValueError(f"duplicate document ids: {duplicated}")
    return docs


def split_of(doc: Doc) -> str:
    """`dev` or `holdout`, stable per document id. While the engine is being improved only `dev`
    failures are looked at; `holdout` is run at the end to measure how much of the gain is
    general (anti-overfit) and how much is tuning to the cases that were studied."""
    return "holdout" if hashlib.sha256(doc.id.encode()).digest()[0] % 2 else "dev"


def is_unsupported(doc: Doc) -> bool:
    return "unsupported" in doc.tags


def is_negative(doc: Doc) -> bool:
    return "negative" in doc.tags


def is_positive(doc: Doc) -> bool:
    return not is_unsupported(doc) and not is_negative(doc)


def validate(docs: list[Doc]) -> list[str]:
    """Problems of the benchmark itself: the truth must match the files, every document must be
    different from every other one, and the counts must be what the benchmark promises."""
    problems = validate_documents([d for d in docs if not is_unsupported(d)])
    seen: dict[str, str] = {}
    for doc in docs:
        digest = hashlib.sha256(doc.content).hexdigest()
        if digest in seen:
            problems.append(f"{doc.id}: byte-identical to {seen[digest]}")
        seen[digest] = doc.id
    for doc in docs:
        if is_positive(doc) and difficulty_of(doc) not in DIFFICULTIES:
            problems.append(f"{doc.id}: no difficulty")
    return problems


def corpus_hash(docs: list[Doc]) -> str:
    digest = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d.id):
        digest.update(doc.id.encode())
        digest.update(doc.content)
    return digest.hexdigest()


def summary(docs: list[Doc]) -> dict[str, Any]:
    positives = [d for d in docs if is_positive(d)]
    by_domain = Counter(d.card for d in positives)
    by_difficulty = Counter(difficulty_of(d) for d in positives)
    tags = Counter(t for d in docs for t in d.tags)
    shapes = {tuple(sorted(d.structure)) for d in docs}
    return {
        "documents": len(docs),
        "positives": len(positives),
        "negatives": sum(1 for d in docs if is_negative(d)),
        "unsupported": sum(1 for d in docs if is_unsupported(d)),
        "by_domain": {DOMAIN_NAMES[k]: by_domain.get(k, 0) for k in DOMAINS},
        "by_difficulty": {k: by_difficulty.get(k, 0) for k in DIFFICULTIES},
        "xlsx": tags["xlsx"],
        "csv": tags["csv"],
        "with_personal_data": sum(1 for d in docs if d.golden.pii_columns),
        "multi_sheet": sum(1 for d in docs if d.sheet_count >= 2),
        "distinct_structures": len(shapes),
        "outcomes": dict(Counter(d.golden.outcome for d in docs)),
        "sha256": corpus_hash(docs),
    }


__all__ = [
    "DOMAINS",
    "DOMAIN_NAMES",
    "build_corpus",
    "corpus_hash",
    "is_negative",
    "is_positive",
    "is_unsupported",
    "manifest",
    "split_of",
    "summary",
    "validate",
]
