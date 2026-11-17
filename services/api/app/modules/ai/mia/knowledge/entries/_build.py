"""Small constructors so that an entry reads as data, not as boilerplate."""

from collections.abc import Mapping

from app.modules.ai.mia.knowledge.types import Anchor, AnchorKind, EntryKind, KnowledgeEntry

_API_PREFIX = "/api/v1/properties/{property_id}"


def route(ref: str) -> Anchor:
    """A Next.js page route, exactly as the folder tree of `apps/web/app` spells it."""
    return Anchor(AnchorKind.WEB_ROUTE, ref)


def tab(ref: str) -> Anchor:
    """A tab id of the Dati page (`apps/web/lib/data/tabs.ts`)."""
    return Anchor(AnchorKind.WEB_TAB, ref)


def copy(ref: str) -> Anchor:
    """A string that must be found, verbatim, in the shipped frontend sources."""
    return Anchor(AnchorKind.WEB_COPY, ref)


def api(method: str, path: str) -> Anchor:
    """A property-scoped API route: `api("GET", "/data/overview")`."""
    return Anchor(AnchorKind.API_ROUTE, f"{method} {_API_PREFIX}{path}")


def enum(ref: str) -> Anchor:
    """A backend enum member: `"app.module.path:EnumClass.MEMBER"`."""
    return Anchor(AnchorKind.ENUM_MEMBER, ref)


def doc(ref: str) -> Anchor:
    """A repository document that must exist."""
    return Anchor(AnchorKind.DOC, ref)


def entry(
    entry_id: str,
    kind: EntryKind,
    title: str,
    summary: str,
    *anchors: Anchor,
    details: tuple[str, ...] = (),
    where: str | None = None,
    page: str | None = None,
    query: Mapping[str, str] | None = None,
    related: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
    not_available: tuple[str, ...] = (),
) -> KnowledgeEntry:
    if not anchors:
        raise ValueError(f"entry {entry_id} has no anchor")
    return KnowledgeEntry(
        id=entry_id,
        kind=kind,
        title=title,
        summary=summary,
        anchors=anchors,
        details=details,
        where=where,
        route=page,
        query=query,
        related=related,
        keywords=keywords,
        not_available=not_available,
    )


SECTION = EntryKind.SECTION
SUBSECTION = EntryKind.SUBSECTION
FEATURE = EntryKind.FEATURE
METRIC = EntryKind.METRIC
STATE = EntryKind.STATE
WORKFLOW = EntryKind.WORKFLOW
TERM = EntryKind.TERM

SIDEBAR = "Barra laterale"

__all__ = [
    "FEATURE",
    "METRIC",
    "SECTION",
    "SIDEBAR",
    "STATE",
    "SUBSECTION",
    "TERM",
    "WORKFLOW",
    "api",
    "copy",
    "doc",
    "entry",
    "enum",
    "route",
    "tab",
]
