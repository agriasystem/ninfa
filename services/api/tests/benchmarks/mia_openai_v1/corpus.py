"""The whole corpus, in a stable order, and the checks that say it is what it claims to be."""

from collections import Counter
from functools import lru_cache

from tests.benchmarks.mia_openai_v1 import (
    corpus_conversation,
    corpus_data,
    corpus_import,
    corpus_product,
    corpus_quality,
    corpus_security,
)
from tests.benchmarks.mia_openai_v1.model import CATEGORY_MINIMUMS, Scenario


@lru_cache(maxsize=1)
def all_scenarios() -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    for module in (
        corpus_product,
        corpus_data,
        corpus_quality,
        corpus_import,
        corpus_security,
        corpus_conversation,
    ):
        scenarios.extend(module.build())
    return tuple(scenarios)


def counts() -> Counter[str]:
    return Counter(s.category for s in all_scenarios())


def shortfalls() -> dict[str, tuple[int, int]]:
    """Categories below their minimum: {category: (have, need)}."""
    have = counts()
    return {c: (have[c], need) for c, need in CATEGORY_MINIMUMS.items() if have[c] < need}


__all__ = ["all_scenarios", "counts", "shortfalls"]
