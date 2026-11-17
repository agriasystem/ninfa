"""The vocabulary of the NINFA Product Knowledge Registry: what NINFA itself IS, as data.

Mia must know every section, feature, state and metric of the CURRENT product, without a system
prompt that someone copied by hand and nobody keeps true. So the knowledge is not prose in a prompt:
it is a registry of small entries, each of which carries ANCHORS - machine-checkable pointers to the
place in the real product where the thing exists (a frontend route, a tab, a piece of shipped copy,
an API route, an enum member). `tests/test_mia_knowledge_registry.py` verifies every anchor against
the code and requires every real route / tab / navigation item / API route group to be anchored by
at least one entry: rename or remove a screen and the test names the obsolete knowledge; add a
screen and the test names the missing one. That is the anti-drift guarantee (ADR 0055).

An entry says what a thing is and where it lives. It never carries a number of any property.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class EntryKind(StrEnum):
    SECTION = "section"  # a screen of the main navigation (Oggi, Decisioni, Dati, ...)
    SUBSECTION = "subsection"  # a tab / block inside a screen (Dati > Costi, Struttura > Fonti)
    FEATURE = "feature"  # something the product does (Smart Import, Source Learning, scope)
    METRIC = "metric"  # a figure the product shows (occupancy, ADR, pickup, CPOR, ...)
    STATE = "state"  # a state or message a person can see ("Analisi parziale", ...)
    WORKFLOW = "workflow"  # how to do something ("change the number of rooms")
    TERM = "term"  # a word of NINFA's vocabulary (observed, reconstructed, ...)


class AnchorKind(StrEnum):
    WEB_ROUTE = "web_route"  # `ref` = a Next.js page route, e.g. "/dati"
    WEB_TAB = "web_tab"  # `ref` = a Dati tab id, e.g. "costs" (apps/web/lib/data/tabs.ts)
    WEB_COPY = "web_copy"  # `ref` = a string that must appear in the shipped frontend copy
    API_ROUTE = "api_route"  # `ref` = "METHOD /api/v1/path" as the OpenAPI spec lists it
    ENUM_MEMBER = "enum_member"  # `ref` = "dotted.module:EnumClass.MEMBER" in the backend
    DOC = "doc"  # `ref` = a repository path of a document that must exist


@dataclass(frozen=True, slots=True)
class Anchor:
    kind: AnchorKind
    ref: str


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """`id` is dotted and stable ("nav.dati", "dati.costs", "metric.occupancy",
    "state.partial_analysis"). `title` is what the interface calls the thing, in Italian. `summary`
    is one or two sentences; `details` are short factual bullets; `where` says how to reach it in
    the interface (only sections
    that really exist); `not_available` says what it does NOT do - so Mia never promises more."""

    id: str
    kind: EntryKind
    title: str
    summary: str
    anchors: tuple[Anchor, ...]
    details: tuple[str, ...] = ()
    where: str | None = None
    route: str | None = None  # the page route when the entry IS a page ("/dati")
    query: Mapping[str, str] | None = None  # e.g. {"tab": "costs"}
    related: tuple[str, ...] = ()
    keywords: tuple[
        str, ...
    ] = ()  # words people use for it, synonyms included (Italian, lower case)
    not_available: tuple[str, ...] = ()


__all__ = ["Anchor", "AnchorKind", "EntryKind", "KnowledgeEntry"]
