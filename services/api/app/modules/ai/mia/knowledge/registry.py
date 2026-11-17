"""The Product Knowledge Registry: a closed, validated set of `KnowledgeEntry`.

Built once (`default_registry()`), immutable. Construction FAILS on a duplicate id or a `related`
pointer to an entry that does not exist, so a broken registry never reaches a request. Whether the
entries are still TRUE of the product is not decided here but by the anti-drift tests, which check
every anchor against the real routes, tabs, copy, API and enums.
"""

from collections.abc import Iterable, Mapping
from functools import lru_cache

from app.modules.ai.mia.knowledge.entries import ALL_ENTRIES
from app.modules.ai.mia.knowledge.search import search_entries
from app.modules.ai.mia.knowledge.types import EntryKind, KnowledgeEntry


class KnowledgeRegistry:
    def __init__(self, entries: Iterable[KnowledgeEntry]) -> None:
        ordered = tuple(entries)
        by_id: dict[str, KnowledgeEntry] = {}
        for entry in ordered:
            if entry.id in by_id:
                raise ValueError(f"duplicate knowledge entry id: {entry.id}")
            by_id[entry.id] = entry
        for entry in ordered:
            for target in entry.related:
                if target not in by_id:
                    raise ValueError(f"entry {entry.id} is related to unknown entry {target}")
        self._entries = ordered
        self._by_id = by_id

    def __len__(self) -> int:
        return len(self._entries)

    def all(self) -> tuple[KnowledgeEntry, ...]:
        return self._entries

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        return self._by_id.get(entry_id)

    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def by_kind(self, kind: EntryKind) -> tuple[KnowledgeEntry, ...]:
        return tuple(entry for entry in self._entries if entry.kind is kind)

    def for_page(self, route: str, query: Mapping[str, str] | None = None) -> KnowledgeEntry | None:
        """The entry that IS the page (and, with a query such as `{"tab": "costs"}`, the more
        specific block of it), or `None`. A query that matches no block falls back to the page."""
        page = next(
            (e for e in self._entries if e.route == route and not e.query),
            None,
        )
        if query:
            for entry in self._entries:
                if (
                    entry.route == route
                    and entry.query
                    and all(query.get(key) == value for key, value in entry.query.items())
                ):
                    return entry
        return page

    def metric_ids(self) -> frozenset[str]:
        return frozenset(e.id for e in self._entries if e.kind is EntryKind.METRIC)

    def search(self, query: str, limit: int = 5) -> tuple[KnowledgeEntry, ...]:
        return search_entries(self._entries, query, limit)


@lru_cache(maxsize=1)
def default_registry() -> KnowledgeRegistry:
    return KnowledgeRegistry(ALL_ENTRIES)


__all__ = ["KnowledgeRegistry", "default_registry"]
