"""Deterministic search over the registry's entries: no model, no embedding, no network.

A person asks "dove cambio il numero di camere?" and the right entry has to come first. The
method is plain and fully reproducible: the question and every entry are reduced to the same
word stems (lower case, no accents, no punctuation, no stop words, endings and plurals cut), and
an entry scores for every stem of the question it contains, weighted by WHERE it contains it
(title, then the words people use for it, then its summary and details) and by how rare the stem
is across the whole registry (a stem found in every entry says nothing). A whole keyword or
title found in the question as a phrase earns a bonus. The same question always gives the same
order; ties keep the registry's own order.

The question is data: it is only ever split into stems and compared, never interpreted, so text
that looks like an instruction changes nothing but its own score.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_TITLE_WEIGHT = 5.0
_KEYWORD_WEIGHT = 4.0
_ID_WEIGHT = 2.0
_SUMMARY_WEIGHT = 2.0
_DETAIL_WEIGHT = 1.0
_LIMIT_WEIGHT = 0.5
_PHRASE_BONUS = 6.0
_TITLE_PHRASE_BONUS = 8.0
_STEM_LENGTH = 6
_MAX_QUERY_CHARS = 400
# A match with fewer than this many stems, out of a longer question, needs a phrase to count.
_MIN_MATCHED = 2
_MIN_RATIO = 0.3
# A keyword this short ("api", "ota") is matched by its stem like any word, never as a phrase.
_MIN_PHRASE_CHARS = 4

# Words that carry no topic in an Italian question about a product.
_STOPWORDS = frozenset(
    (
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "uno",
        "una",
        "di",
        "a",
        "da",
        "in",
        "con",
        "su",
        "per",
        "tra",
        "fra",
        "e",
        "ed",
        "o",
        "ma",
        "se",
        "che",
        "chi",
        "cui",
        "non",
        "ho",
        "hai",
        "ha",
        "hanno",
        "sono",
        "sei",
        "siamo",
        "siete",
        "era",
        "ero",
        "mi",
        "ti",
        "ci",
        "vi",
        "si",
        "me",
        "te",
        "lui",
        "lei",
        "noi",
        "voi",
        "del",
        "dello",
        "della",
        "dei",
        "degli",
        "delle",
        "al",
        "allo",
        "alla",
        "ai",
        "agli",
        "alle",
        "dal",
        "dallo",
        "dalla",
        "dai",
        "dagli",
        "dalle",
        "nel",
        "nello",
        "nella",
        "nei",
        "negli",
        "nelle",
        "sul",
        "sullo",
        "sulla",
        "sui",
        "sugli",
        "sulle",
        "mio",
        "mia",
        "miei",
        "mie",
        "tuo",
        "tua",
        "suo",
        "sua",
        "nostro",
        "nostra",
        "questo",
        "questa",
        "questi",
        "queste",
        "quello",
        "quella",
        "quelli",
        "quelle",
        "ogni",
        "tutto",
        "tutti",
        "tutte",
        "tutta",
        "anche",
        "ancora",
        "gia",
        "solo",
        "molto",
        "poco",
        "piu",
        "meno",
        "come",
        "dove",
        "cosa",
        "cose",
        "cos",
        "quale",
        "quali",
        "quando",
        "quanto",
        "quanta",
        "quanti",
        "quante",
        "perche",
        "mai",
        "puo",
        "possono",
        "posso",
        "possiamo",
        "devo",
        "deve",
        "dobbiamo",
        "faccio",
        "fa",
        "fanno",
        "fare",
        "vedo",
        "vedi",
        "vede",
        "vedere",
        "trovo",
        "trova",
        "trovare",
        "voglio",
        "vorrei",
        "vuole",
        "vuoi",
        "ninfa",
        "mia",
        "c",
        "l",
        "d",
        "s",
        "t",
        "un",
        "po",
        "dimmi",
        "dammi",
        "fammi",
        "spiegami",
        "spiega",
        "spiegare",
        "dire",
        "dici",
    )
)


def normalize(text: str) -> str:
    """Lower case, no accents, every apostrophe and symbol a space, single spaces."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    cleaned = re.sub(r"[^a-z0-9]+", " ", plain)
    return re.sub(r"\s+", " ", cleaned).strip()


def stem(word: str) -> str:
    """A crude Italian stem: an infinitive ending dropped, up to two final vowels dropped, then
    cut. Enough to match singular/plural and the verb/noun forms the registry uses
    (camera/camere, importare/importa, cambiare/cambio)."""
    if word.isdigit() or len(word) <= 3:
        return word
    trimmed = word
    if len(trimmed) > 6 and trimmed.endswith(("are", "ere", "ire")):
        trimmed = trimmed[:-3]
    for _ in range(2):
        if len(trimmed) > 4 and trimmed[-1] in "aeiou":
            trimmed = trimmed[:-1]
    return trimmed[:_STEM_LENGTH]


def stems_of(text: str) -> tuple[str, ...]:
    """The distinct stems of a text, in order of first appearance, stop words removed."""
    seen: dict[str, None] = {}
    for word in normalize(text).split():
        if word in _STOPWORDS:
            continue
        seen.setdefault(stem(word), None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class _Indexed:
    entry: KnowledgeEntry
    title: frozenset[str]
    keywords: frozenset[str]
    ident: frozenset[str]
    summary: frozenset[str]
    detail: frozenset[str]
    limits: frozenset[str]
    title_text: str
    keyword_phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Index:
    source: Sequence[KnowledgeEntry]
    items: tuple[_Indexed, ...]
    idf: dict[str, float]


_CACHE: dict[int, _Index] = {}


def _index(entries: Sequence[KnowledgeEntry]) -> _Index:
    cached = _CACHE.get(id(entries))
    if cached is not None and cached.source is entries:
        return cached
    items: list[_Indexed] = []
    frequency: Counter[str] = Counter()
    for entry in entries:
        title = frozenset(stems_of(entry.title))
        keywords = frozenset(s for phrase in entry.keywords for s in stems_of(phrase))
        ident = frozenset(stems_of(entry.id.replace(".", " ").replace("_", " ")))
        summary = frozenset(stems_of(entry.summary))
        detail = frozenset(
            s for line in (*entry.details, entry.where or "") for s in stems_of(line)
        )
        limits = frozenset(s for line in entry.not_available for s in stems_of(line))
        items.append(
            _Indexed(
                entry=entry,
                title=title,
                keywords=keywords,
                ident=ident,
                summary=summary,
                detail=detail,
                limits=limits,
                title_text=normalize(entry.title),
                keyword_phrases=tuple(
                    normalize(k) for k in entry.keywords if len(normalize(k)) > _MIN_PHRASE_CHARS
                ),
            )
        )
        frequency.update(title | keywords | ident | summary | detail)
    total = max(len(items), 1)
    idf = {word: math.log(1 + total / count) for word, count in frequency.items()}
    index = _Index(source=entries, items=tuple(items), idf=idf)
    _CACHE[id(entries)] = index
    return index


def _score(
    item: _Indexed, query_stems: tuple[str, ...], plain_query: str, idf: dict[str, float]
) -> float:
    score = 0.0
    matched = 0
    for word in query_stems:
        weight = idf.get(word, 1.0)
        if word in item.title:
            score += _TITLE_WEIGHT * weight
        elif word in item.keywords:
            score += _KEYWORD_WEIGHT * weight
        elif word in item.ident:
            score += _ID_WEIGHT * weight
        elif word in item.summary:
            score += _SUMMARY_WEIGHT * weight
        elif word in item.detail:
            score += _DETAIL_WEIGHT * weight
        elif word in item.limits:
            score += _LIMIT_WEIGHT * weight
        else:
            continue
        matched += 1
    padded = f" {plain_query} "
    phrase = 0.0
    if item.title_text and f" {item.title_text} " in padded:
        phrase += _TITLE_PHRASE_BONUS
    for keyword in item.keyword_phrases:
        if f" {keyword} " in padded:
            phrase += _PHRASE_BONUS
    # A whole title or keyword in the question is relevant on its own. Otherwise one stray stem
    # out of a long question is noise (it is how an off-topic or hostile text scores something).
    if phrase == 0.0 and matched < _MIN_MATCHED and matched / max(len(query_stems), 1) < _MIN_RATIO:
        return 0.0
    return score + phrase


def search_entries(
    entries: Sequence[KnowledgeEntry], query: str, limit: int = 5
) -> tuple[KnowledgeEntry, ...]:
    """The best `limit` entries for `query`, best first; nothing when no word of it matches."""
    text = query[:_MAX_QUERY_CHARS]
    query_stems = stems_of(text)
    if limit <= 0 or not normalize(text):
        return ()
    index = _index(entries)
    plain_query = normalize(text)
    scored = [
        (_score(item, query_stems, plain_query, index.idf), position, item.entry)
        for position, item in enumerate(index.items)
    ]
    ranked = sorted((row for row in scored if row[0] > 0.0), key=lambda row: (-row[0], row[1]))
    return tuple(entry for _, _, entry in ranked[:limit])


__all__ = ["normalize", "search_entries", "stem", "stems_of"]
