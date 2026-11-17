"""Product support tools: what NINFA itself IS, answered from the Product Knowledge Registry.

    search_ninfa_knowledge   "dove cambio il numero di camere?" -> the entries that answer it
    get_page_help            what the screen the person is on is for and what can be done there
    get_feature_explanation  one entry in full, by its id
    get_ninfa_glossary       what a NINFA word means, or the whole glossary

None of them reads a property: they carry no figure of any hotel, and an entry is only ever repeated
as the registry wrote it (every entry is anchored to the real routes, tabs, copy, API and enums, and
a test fails when one goes stale). That is what lets Mia talk about the product without a manual in
her prompt, and what keeps her from describing a screen that does not exist.
"""

import difflib
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry, default_registry
from app.modules.ai.mia.knowledge.types import EntryKind, KnowledgeEntry
from app.modules.ai.mia.tools.base import ToolDefinition, ToolRuntime
from app.modules.ai.mia.types import Observation

REF_PREFIX = "knowledge:ninfa:"

_KIND_WORDS: dict[EntryKind, str] = {
    EntryKind.SECTION: "sezione",
    EntryKind.SUBSECTION: "sottosezione",
    EntryKind.FEATURE: "funzione",
    EntryKind.METRIC: "metrica",
    EntryKind.STATE: "stato o messaggio",
    EntryKind.WORKFLOW: "procedura",
    EntryKind.TERM: "termine",
}
_GLOSSARY_KINDS = frozenset({EntryKind.TERM, EntryKind.METRIC, EntryKind.STATE})

_NOTES = (
    "Sono informazioni sul prodotto NINFA, non sui dati della struttura: nessuna cifra qui è della "
    "struttura.",
    "Descrivi solo ciò che le voci dicono. Se una funzione non compare qui, NINFA non la ha: non "
    "inventarla e non promettere di averla.",
)
_NO_MATCH = (
    "Nessuna voce della conoscenza di NINFA corrisponde alla domanda: non esiste una funzione "
    "con quel nome che io possa descrivere. Non inventarla.",
)
_MAX_RELATED = 6
_MAX_DETAILS = 8
_ROUTE_DECISION_DETAIL = re.compile(r"^/oggi/decisioni/[^/]+$")


def _ref(entry: KnowledgeEntry) -> str:
    return f"{REF_PREFIX}{entry.id}"


def _title_of(registry: KnowledgeRegistry, entry_id: str) -> dict[str, str] | None:
    found = registry.get(entry_id)
    return None if found is None else {"id": found.id, "titolo": found.title}


def _view(entry: KnowledgeEntry, registry: KnowledgeRegistry, *, full: bool) -> dict[str, Any]:
    """An entry as the model reads it. `full=False` is the compact form (a list of candidates)."""
    view: dict[str, Any] = {
        "id": entry.id,
        "titolo": entry.title,
        "tipo": _KIND_WORDS[entry.kind],
        "cosa_e": entry.summary,
    }
    if entry.where:
        view["dove_si_trova"] = entry.where
    if not full:
        return view
    if entry.details:
        view["dettagli"] = list(entry.details[:_MAX_DETAILS])
    if entry.not_available:
        view["limiti"] = list(entry.not_available)
    related = [
        item
        for item in (_title_of(registry, target) for target in entry.related[:_MAX_RELATED])
        if item is not None
    ]
    if related:
        view["voci_collegate"] = related
    return view


def _limits_of(entries: Iterable[KnowledgeEntry]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(line for entry in entries for line in entry.not_available))


def _observation(
    tool: str,
    entries: tuple[KnowledgeEntry, ...],
    data: dict[str, Any],
    resolved: dict[str, Any],
    *,
    extra_limits: tuple[str, ...] = (),
) -> Observation:
    return Observation(
        tool=tool,
        refs=tuple(_ref(entry) for entry in entries),
        data=data,
        not_available=(*extra_limits, *_limits_of(entries)),
        notes=_NOTES,
        resolved=resolved,
        kind="product",
    )


# --- search_ninfa_knowledge ----------------------------------------------------------------------


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "La domanda o le parole da cercare, come le direbbe la persona "
            "(per esempio: 'dove cambio il numero di camere')."
        ),
    )
    limit: int = Field(
        default=4, ge=1, le=6, description="Quante voci al massimo restituire (default 4)."
    )


def _search(runtime: ToolRuntime, args: SearchKnowledgeArgs) -> Observation:
    found = runtime.registry.search(args.query, args.limit)
    # what the conversation remembers of this call is WHICH entries answered, never the text asked
    # (that text is the person's, and it would come back into the next turn's history)
    resolved: dict[str, Any] = {"voci": [entry.id for entry in found]}
    if not found:
        return Observation(
            tool="search_ninfa_knowledge",
            refs=(),
            data={"risultati": []},
            not_available=_NO_MATCH,
            notes=_NOTES,
            resolved=resolved,
            kind="product",
        )
    return _observation(
        "search_ninfa_knowledge",
        found,
        {"risultati": [_view(entry, runtime.registry, full=True) for entry in found]},
        resolved,
    )


# --- get_page_help -------------------------------------------------------------------------------


def _canonical_route(route: str) -> str:
    path = route.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
    return "/oggi/decisioni/[decisionId]" if _ROUTE_DECISION_DETAIL.match(path) else path


class PageHelpArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "La pagina di NINFA, per esempio '/dati' o '/struttura'. Se la ometti si usa la pagina "
            "in cui la persona si trova adesso (se nota)."
        ),
    )
    section: str | None = Field(
        default=None,
        max_length=40,
        pattern=r"^[a-z0-9_\-]+$",
        description=(
            "La scheda o il blocco della pagina: per /dati una tra overview, bookings, "
            "distribution, costs, labor; per /struttura per esempio struttura-rooms."
        ),
    )


def _section_query(route: str, section: str) -> dict[str, str]:
    return {"tab": section} if route == "/dati" else {"section": section}


def _navigation_entries(registry: KnowledgeRegistry) -> tuple[KnowledgeEntry, ...]:
    return tuple(
        entry for entry in registry.by_kind(EntryKind.SECTION) if entry.id != "nav.decision_detail"
    )


def _page_help(runtime: ToolRuntime, args: PageHelpArgs) -> Observation:
    registry = runtime.registry
    page_context = runtime.page
    route = _canonical_route(args.route) if args.route else page_context.route
    section = args.section if args.route or args.section else page_context.section

    page = registry.for_page(route) if route else None
    if page is None:
        menu = _navigation_entries(registry)
        resolved: dict[str, Any] = {"voci": []}
        reason = (
            "Non so in quale pagina di NINFA si trovi la persona."
            if route is None
            else "Quella pagina non esiste in NINFA."
        )
        return _observation(
            "get_page_help",
            menu,
            {"pagine": [_view(entry, registry, full=False) for entry in menu]},
            resolved,
            extra_limits=(
                reason,
                "Indica le sezioni che esistono davvero, senza inventare altre pagine.",
            ),
        )

    blocks: list[KnowledgeEntry] = [page]
    specific = (
        registry.for_page(route, _section_query(route, section)) if route and section else None
    )
    if specific is not None and specific.id != page.id:
        blocks.append(specific)

    data: dict[str, Any] = {"pagina": _view(page, registry, full=True)}
    if len(blocks) > 1:
        data["sezione_aperta"] = _view(blocks[1], registry, full=True)
    elif section:
        data["sezione_aperta"] = None
    selected = blocks.copy()
    if page_context.metric_id and page_context.route == route:
        metric = registry.get(page_context.metric_id)
        if metric is not None:
            data["metrica_selezionata"] = _view(metric, registry, full=False)
            selected.append(metric)
    resolved = {"voci": [entry.id for entry in selected]}
    return _observation("get_page_help", tuple(selected), data, resolved)


# --- get_feature_explanation ---------------------------------------------------------------------


def _closest_ids(entry_id: str) -> list[str]:
    registry = default_registry()
    close = difflib.get_close_matches(entry_id, sorted(registry.ids()), n=5, cutoff=0.4)
    spoken = entry_id.replace(".", " ").replace("_", " ")
    close.extend(entry.id for entry in registry.search(spoken, 5))
    return list(dict.fromkeys(close))[:6]


class FeatureExplanationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9_.]+$",
        description=(
            "L'identificativo di una voce di conoscenza ottenuto da search_ninfa_knowledge "
            "(per esempio 'metric.pickup' o 'import.scope')."
        ),
    )

    @field_validator("entry_id")
    @classmethod
    def _must_exist(cls, value: str) -> str:
        if default_registry().get(value) is None:
            hints = ", ".join(_closest_ids(value)) or "nessuna voce simile"
            raise ValueError(f"unknown entry id; the closest ids are: {hints}")
        return value


def _explain(runtime: ToolRuntime, args: FeatureExplanationArgs) -> Observation:
    entry = runtime.registry.get(args.entry_id)
    resolved: dict[str, Any] = {"voci": [args.entry_id]}
    if entry is None:  # a registry other than the default one was handed to the runtime
        hints = ", ".join(_closest_ids(args.entry_id)) or "nessuna voce simile"
        return Observation(
            tool="get_feature_explanation",
            refs=(),
            data={},
            not_available=(f"Nessuna voce con id {args.entry_id}; le più simili: {hints}.",),
            notes=_NOTES,
            resolved=resolved,
            kind="product",
        )
    return _observation(
        "get_feature_explanation",
        (entry,),
        {"voce": _view(entry, runtime.registry, full=True)},
        resolved,
    )


# --- get_ninfa_glossary --------------------------------------------------------------------------


class GlossaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description=(
            "La parola o l'espressione di NINFA di cui si vuole il significato "
            "(per esempio 'dato ricostruito', 'on-books', 'camere-notte'). "
            "Se la ometti si ottiene l'elenco dei termini."
        ),
    )


def _glossary(runtime: ToolRuntime, args: GlossaryArgs) -> Observation:
    registry = runtime.registry
    if args.term is None:
        terms = registry.by_kind(EntryKind.TERM)
        return _observation(
            "get_ninfa_glossary",
            (),
            {"termini": [_view(entry, registry, full=False) for entry in terms]},
            {"voci": []},
        )
    pool = tuple(entry for entry in registry.all() if entry.kind in _GLOSSARY_KINDS)
    # the registry's own search, restricted to words, metrics and states
    found = tuple(entry for entry in registry.search(args.term, 24) if entry in pool)[:4]
    resolved: dict[str, Any] = {"voci": [entry.id for entry in found]}
    if not found:
        return Observation(
            tool="get_ninfa_glossary",
            refs=(),
            data={"termini": []},
            not_available=(
                "Questa parola non è nel glossario di NINFA: non darne una definizione come "
                "se lo fosse. Se è un concetto generale di hospitality puoi spiegarlo, dicendo "
                "che non è un termine di NINFA.",
            ),
            notes=_NOTES,
            resolved=resolved,
            kind="product",
        )
    return _observation(
        "get_ninfa_glossary",
        found,
        {"termini": [_view(entry, registry, full=True) for entry in found]},
        resolved,
    )


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="search_ninfa_knowledge",
        description=(
            "Cerca nella conoscenza del prodotto NINFA: dove si trova una funzione, come si fa "
            "qualcosa, cosa significa un messaggio, una metrica o un termine, che file si possono "
            "importare. Usalo per ogni domanda su COME FUNZIONA NINFA o DOVE SI TROVA qualcosa. "
            "Non contiene dati della struttura."
        ),
        domain=AccessDomain.PRODUCT,
        args_model=SearchKnowledgeArgs,
        handler=_search,
    ),
    ToolDefinition(
        name="get_page_help",
        description=(
            "A cosa serve una pagina di NINFA e cosa si può fare lì. Senza argomenti descrive la "
            "pagina in cui la persona si trova adesso (se è nota), compresa la scheda aperta e la "
            "metrica selezionata. Usalo per 'cosa vedo qui?', 'a cosa serve questa pagina?'."
        ),
        domain=AccessDomain.PRODUCT,
        args_model=PageHelpArgs,
        handler=_page_help,
    ),
    ToolDefinition(
        name="get_feature_explanation",
        description=(
            "La spiegazione completa di UNA voce di conoscenza di NINFA, dato il suo id (lo trovi "
            "con search_ninfa_knowledge o tra le voci collegate). Usalo per approfondire."
        ),
        domain=AccessDomain.PRODUCT,
        args_model=FeatureExplanationArgs,
        handler=_explain,
    ),
    ToolDefinition(
        name="get_ninfa_glossary",
        description=(
            "Il significato di una parola di NINFA (dato osservato, dato ricostruito, on-books, "
            "camere-notte, scope...). Senza termine restituisce l'elenco dei termini. Per un "
            "concetto generale di hospitality non serve: spiegalo tu, senza dire che è di NINFA."
        ),
        domain=AccessDomain.PRODUCT,
        args_model=GlossaryArgs,
        handler=_glossary,
    ),
)

__all__ = ["REF_PREFIX", "TOOLS"]
