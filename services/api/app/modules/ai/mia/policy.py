"""The reasoning policy of Mia: how hard the model thinks about THIS call. Chosen by the
application, deterministically, never by the model, and never "high for every message".

    LOW      a pointer or a definition: "dove trovo...", "cos'e'...", "come cambio il numero di
             camere", "che differenza c'e' tra FULL e DELTA". Nothing about the property's numbers.
    MEDIUM   the default: interpreting a figure, explaining a decision, one comparison, an operating
             question about the property.
    HIGH     a question that has to join several areas (revenue + costs + distribution + staff), or
             asks for an analysis / a diagnosis / a summary of the whole situation - and a turn that
             in fact consulted three or more areas, whatever the wording was.

Two moments, one rule each:

* `initial(question)` is read from the wording alone, BEFORE any tool ran (it sets the effort of the
  first model call, which has to plan);
* `after_tools(...)` is read from what the turn really consulted (it sets the effort of the call
that
  writes the answer): a "LOW" question that needed numbers is at least MEDIUM, and any turn that
  gathered evidence from three or more areas is HIGH.

This is a heuristic on purpose, kept small and readable so it can be measured and changed: its
failures cost tokens or depth, never correctness (the numeric grounding guard and the closed tool
catalog do not depend on it).
"""

import re
import unicodedata

from app.modules.ai.gateway.tool_protocol import ReasoningLevel

# Areas of NINFA a question can touch, by the words people use for them.
_AREAS: dict[str, tuple[str, ...]] = {
    "ricavi": (
        r"ricav",
        r"occupaz",
        r"\badr\b",
        r"prenotaz",
        r"pickup",
        r"camere",
        r"notti",
        r"tariff",
        r"prezz",
        r"vendend",
        r"vendit",
    ),
    "distribuzione": (
        r"\bota\b",
        r"booking",
        r"expedia",
        r"canal",
        r"dirett",
        r"distribuzion",
        r"commission",
    ),
    "costi": (r"\bcost", r"cpor", r"spes[ae]", r"fattur"),
    "personale": (r"personale", r"\bore\b", r"\bstaff", r"turn[io]", r"reparto", r"reparti"),
}

# Wording of a request for analysis, a diagnosis or the whole picture.
_ANALYSIS = (
    r"\banalizz",
    r"\banalisi (di|del|dei|della|delle|sul|sulla|completa|approfondita)\b",
    r"diagnos",
    r"riepilog",
    r"riassum",
    r"situazione",
    r"panoramica",
    r"confront",
    r"problema piu importante",
    r"dove devo concentrarmi",
    r"su cosa devo",
    r"sto guadagnando",
    r"come sta andando",
    r"andando (male|bene)",
    r"cosa non va",
    r"che cosa non va",
)

# Wording of "where is / what is / how do I", i.e. product support and definitions.
_SUPPORT = (
    r"^dove (trovo|si trova|posso|vado|devo andare)",
    r"^come (faccio|si fa|posso|cambio|modifico|correggo|configuro|importo|carico|aggiungo)",
    r"^cos e\b",
    r"^cosa e\b",
    r"^che cos e\b",
    r"^(cosa|che cosa) (significa|vuol dire|vuole dire|puo fare|puoi fare|sai fare|fa)",
    r"^che differenza",
    r"^a cosa serve",
    r"^come funziona",
    r"^(che|quali) file",
    r"^cosa deve contenere",
    r"^spiegami (cos|cosa|il significato|la differenza)",
)

# A support-looking question that is really about THIS property or day is a data question.
_PROPERTY_SPECIFIC = (
    r"\b(oggi|ieri|domani|dopodomani|stasera|stamattina)\b",
    r"\b(il|la|le|i) (mio|mia|miei|mie|nostro|nostra)\b",
    r"\b(mio|mia|miei|mie|nostro|nostra|nostri|nostre)\b",
    r"settiman",
    r"\bmese\b",
    r"prossim[aeio]",
    r"scors[aeio]",
    r"\bperche\b",
)

_LONG_QUESTION_CHARS = 260
_SHORT_QUESTION_CHARS = 140
_AREAS_FOR_HIGH = 2
_DOMAINS_FOR_HIGH_AFTER_TOOLS = 3


def _plain(text: str) -> str:
    """Lower case, no accents, apostrophes as spaces: the patterns above are typed without them."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", stripped.replace("'", " ").replace("’", " ")).strip()


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def areas_mentioned(question: str) -> frozenset[str]:
    plain = _plain(question)
    return frozenset(name for name, patterns in _AREAS.items() if _matches(plain, patterns))


def initial(question: str) -> ReasoningLevel:
    """The effort of the first call, from the wording alone."""
    plain = _plain(question)
    if len(plain) > _LONG_QUESTION_CHARS:
        return "high"
    if _matches(plain, _ANALYSIS) or len(areas_mentioned(plain)) >= _AREAS_FOR_HIGH:
        return "high"
    if (
        len(plain) <= _SHORT_QUESTION_CHARS
        and _matches(plain, _SUPPORT)
        and not _matches(plain, _PROPERTY_SPECIFIC)
    ):
        return "low"
    return "medium"


_ORDER: dict[ReasoningLevel, int] = {"low": 0, "medium": 1, "high": 2}


def _at_least(level: ReasoningLevel, floor: ReasoningLevel) -> ReasoningLevel:
    return level if _ORDER[level] >= _ORDER[floor] else floor


def after_tools(
    current: ReasoningLevel, *, data_domains: int, used_data_tool: bool
) -> ReasoningLevel:
    """The effort of the calls that follow tool results, from what the turn really consulted."""
    level = current
    if used_data_tool:
        level = _at_least(level, "medium")
    if data_domains >= _DOMAINS_FOR_HIGH_AFTER_TOOLS:
        level = _at_least(level, "high")
    return level


__all__ = ["after_tools", "areas_mentioned", "initial"]
