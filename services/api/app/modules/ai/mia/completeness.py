"""Deterministic checks that an answer is COMPLETE: written to its end, and honest about what the
figures it rests on cannot say.

1. TRUNCATION. The structured output of a real model can, rarely, stop in the middle of a sentence
   while still being valid JSON with status ANSWERED (measured against the real API: one answer in
   ~50 ended "...e non esistono"). A cut-off answer is worse than a short one - it reads as a
   statement the user cannot see the end of - so it never goes out: the orchestrator asks for a
   rewrite once (like an ungrounded figure) and fails closed if the rewrite is cut off too. The
   rule is deliberately plain and measured: every answer of the real-model runs ended with a full
   stop or a question mark. An answer is complete when its last character closes a sentence, or
   when its last line is a list item ("- ..."), which is written without a full stop.

2. MATERIAL GAPS ("truthfulness closure", ADR 0055). A person asks for a METRIC and NINFA holds only
   a component of it: 14 rooms booked for Friday, but no room inventory, so no occupancy
   percentage. The honest answer gives the 14 AND says the percentage cannot be calculated, and why.
   A model that is only ASKED to do so (the system policy does) did not always: a short question
   got the nearest figure and nothing else. So the application decides, in code:

   * the TOOL declares the gap (`Observation.gaps`: which metric, why, whether it is partial),
     from what it really read - the model is not trusted to notice a `None`;
   * the gap is MATERIAL only when the person ASKED for that metric (`asked_by`): this question,
     or - for a follow-up with no metric of its own ("E sabato?") - the question before it. A
     gap nobody asked about is not announced: no answer becomes a disclaimer;
   * the answer ACKNOWLEDGES it when one of its sentences names the metric (or the missing input)
     and says it is missing or partial (`named_by` + a negation / partiality word);
   * when it does not, the orchestrator ADDS the sentence, written from the tool's own reason. No
     figure is estimated, and no model call is spent.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.modules.ai.mia.types import Gap

# --- 1. truncation --------------------------------------------------------------------------------

_SENTENCE_END = (".", "!", "?", "…", ")", '"', "»", "”", ":")


def looks_truncated(answer: str) -> bool:
    """True when `answer` ends without closing its last sentence."""
    text = answer.rstrip()
    if not text:
        return False  # emptiness is another check's job (answer validation)
    if text.endswith(_SENTENCE_END):
        return False
    last_line = text.splitlines()[-1].lstrip()
    return not last_line.startswith("- ")


# --- 2. material gaps -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GapMetric:
    """One metric a tool can be unable to give.

    `label`     what the metric is called in a sentence, with its article ("l'occupazione ...");
    `asked_by`  how a person asks for it ("pieni" is how an owner asks for the occupancy);
    `named_by`  how an honest answer names it or the input it lacks ("inventario", "capienza").

    `asked_by` and `named_by` are WORD STARTS, lower case, matched at the start of a word (so
    "occupa" meets "occupazione" and "occupate"; a stem with a space is a phrase).
    """

    label: str
    asked_by: tuple[str, ...]
    named_by: tuple[str, ...]


GAP_METRICS: Mapping[str, GapMetric] = {
    "metric.occupancy": GapMetric(
        label="l'occupazione in percentuale",
        asked_by=("occupa", "pien", "riempi", "satur"),
        named_by=(
            "occupa",
            "percentual",
            "inventario",
            "capienza",
            "disponibil",
            "vendibil",
            "numero di camere",
            "camere totali",
        ),
    ),
    "metric.cpor": GapMetric(
        label="il costo per camera occupata",
        asked_by=(
            "cpor",
            "costo per camera",
            "costo per ogni camera",
            "costo camera",
            "costi per camera",
            "costo medio per camera",
            "costo medio a camera",
            "costo a camera",
            "camera occupata",
            "ogni camera",
            "costa una camera",
            "costo di una camera",
        ),
        named_by=(
            "cpor",
            "costo per camera",
            "camera occupata",
            "camere occupate",
            "occupazione",
            "inventario",
        ),
    ),
    "metric.labor_incidence": GapMetric(
        label="l'incidenza del costo del personale sui ricavi",
        asked_by=(
            "incidenz",
            "sui ricavi",
            "rispetto ai ricavi",
            "pesa il personale",
            "personale pesa",
            "pesa il costo del personale",
            "ricavo per ora",
            "ricavi per ora",
            "produttivit",
        ),
        named_by=("incidenz", "ricav", "confront"),
    ),
    "metric.pickup": GapMetric(
        label="il pickup (la variazione delle camere prenotate su una settimana)",
        asked_by=(
            "pickup",
            "pick-up",
            "pick up",
            "nuove prenotazioni",
            "prenotazioni nuove",
            "rallent",
            "ritmo",
            "variazion",
        ),
        named_by=(
            "pickup",
            "variazion",
            "una settimana fa",
            "7 giorni fa",
            "osservazion",
            "dati nuovi",
            "dato nuovo",
            "ritmo",
        ),
    ),
    "metric.period_comparison": GapMetric(
        label=(
            "il confronto con lo stesso periodo dell'anno scorso, con il mese precedente o con "
            "un budget"
        ),
        asked_by=(
            "anno scorso",
            "anno precedente",
            "anno prima",
            "un anno fa",
            "scorso anno",
            "stesso periodo",
            "mese scorso",
            "mese precedente",
            "budget",
            "yoy",
            "year over year",
        ),
        named_by=(
            "confront",
            "anno scorso",
            "anno precedente",
            "anno prima",
            "budget",
            "mese precedente",
            "mese scorso",
            "stesso periodo",
            "storic",
        ),
    ),
    "metric.ota_share": GapMetric(
        label="la quota OTA",
        asked_by=(
            "quota ota",
            "percentuale ota",
            "dipendenza ota",
            "dipendenza dalle ota",
            "dipendiamo dalle ota",
            "peso delle ota",
            "pesano le ota",
            "ota",
        ),
        named_by=("quota", "ota", "dipendenza", "percentual", "insufficient"),
    ),
    "metric.channel_weight": GapMetric(
        label="il peso di ogni canale",
        asked_by=(
            "peso dei canali",
            "peso di ogni canale",
            "peso del canale",
            "pesa ogni canale",
            "pesano i canali",
            "canali",
            "canale",
            "booking.com",
            "expedia",
        ),
        named_by=("canal", "peso", "pesi", "percentual", "composizione"),
    ),
}

# Said in a sentence that names the metric, these make it an acknowledgement of a MISSING figure;
# a PARTIAL one is acknowledged by these or by the words that say "only part".
_ABSENCE = (
    "manca",
    "mancan",
    "senza",
    "impossibil",
    "nessun",
    "ignot",
    "sconosc",
    "indisponibil",
    "incalcolabil",
    "assent",
    "non conosc",
    "non posso",
    "non riesco",
    "non è",
    "non si può",
    "non si puo",
    "non ho",
    "non c'è",
    "non ci sono",
    "non risulta",
    "non disponibil",
    "non calcolabil",
    "non noto",
    "non nota",
)
_PARTIALITY = (
    *_ABSENCE,
    "solo",
    "soltanto",
    "parzial",
    "alcune",
    "alcuni",
    "incomplet",
    "non tutte",
    "non tutti",
)
_SENTENCES = re.compile(r"[.!?;\n]+")


def _starts_word(text: str, stem: str) -> bool:
    """`stem` found at the start of a word of `text` (already lower case)."""
    return re.search(r"(?<!\w)" + re.escape(stem), text) is not None


def _mentions_any(text: str, stems: Iterable[str]) -> bool:
    return any(_starts_word(text, stem) for stem in stems)


def asked_for(metric: str, question: str, earlier_question: str = "") -> bool:
    """Did the person ask for this metric? The question itself when it names ANY metric of the
    table (it says what it wants); a question that names none ("E sabato?") continues the one before
    it. An unknown metric was asked by nobody."""
    spec = GAP_METRICS.get(metric)
    if spec is None:
        return False
    current = question.lower()
    if _mentions_any(current, spec.asked_by):
        return True
    names_a_metric = any(_mentions_any(current, other.asked_by) for other in GAP_METRICS.values())
    return not names_a_metric and _mentions_any(earlier_question.lower(), spec.asked_by)


def acknowledges(metric: str, answer: str, *, partial: bool = False) -> bool:
    """Does one sentence of `answer` name the metric (or what it lacks) AND say it is missing (or,
    for a partial figure, partial)? Plain on purpose: a false "yes" needs a sentence about the same
    subject that denies something else; a false "no" only costs one more, true, sentence."""
    spec = GAP_METRICS.get(metric)
    if spec is None:
        return True
    markers = _PARTIALITY if partial else _ABSENCE
    for sentence in _SENTENCES.split(answer.lower()):
        if _mentions_any(sentence, spec.named_by) and any(marker in sentence for marker in markers):
            return True
    return False


def _material_gaps(gaps: Iterable[Gap], question: str, earlier_question: str) -> dict[str, Gap]:
    """The gaps the person ASKED about: one per metric (the most severe - a missing figure before a
    partial one - wins), in the order the tools reported."""
    chosen: dict[str, Gap] = {}
    for gap in gaps:
        if not asked_for(gap.metric, question, earlier_question):
            continue
        known = chosen.get(gap.metric)
        if known is None or (known.partial and not gap.partial):
            chosen[gap.metric] = gap
    return chosen


def undisclosed_gaps(
    gaps: Iterable[Gap], *, question: str, earlier_question: str = "", answer: str
) -> list[Gap]:
    """The gaps the person ASKED about that `answer` does not acknowledge at all."""
    chosen = _material_gaps(gaps, question, earlier_question)
    return [
        gap for gap in chosen.values() if not acknowledges(gap.metric, answer, partial=gap.partial)
    ]


def names_the_need(gap: Gap, answer: str) -> bool:
    """Does `answer` name WHAT is missing ("l'inventario camere")? A gap that declares no `needs` is
    explained by its own label, and always passes."""
    return not gap.needs or _mentions_any(answer.lower(), gap.needs)


def _flat(reason: str) -> str:
    """A reason is ONE clause: a colon inside it (the Dati page's own sentences have some) would
    read as a second colon after the one that introduces it."""
    return reason.replace(": ", ", ")


def _label(metric: str) -> str:
    spec = GAP_METRICS.get(metric)
    return spec.label if spec is not None else "questo dato"


def gap_statement(gap: Gap) -> str:
    """The gap as the MODEL reads it in the tool result ("non disponibile"): one sentence."""
    label = _label(gap.metric)
    head = label[:1].upper() + label[1:]
    if gap.partial:
        return f"{head} è parziale: {_flat(gap.reason)}."
    return f"{head} non è calcolabile: {_flat(gap.reason)}."


def gap_disclosure(gap: Gap) -> str:
    """The same gap as MIA says it to the person: one sentence, no figure that is not the tool's."""
    label = _label(gap.metric)
    if gap.partial:
        return f"Tieni presente che {label} è parziale: {_flat(gap.reason)}."
    return f"Non posso però calcolare {label}: {_flat(gap.reason)}."


def gap_reason(gap: Gap) -> str:
    """Only the reason, for an answer that already said the metric is missing (or partial) but not
    what is missing: a live run said "L'occupazione non è calcolabile." and stopped there."""
    lead = "Nel dettaglio" if gap.partial else "Il dato che manca"
    return f"{lead}: {_flat(gap.reason)}."


def disclosures_for(
    gaps: Iterable[Gap], *, question: str, earlier_question: str = "", answer: str
) -> list[str]:
    """What the application must ADD to `answer`, as sentences, so that a person who asked for a
    metric reads three things: what is known (the answer), that the metric cannot be calculated (or
    is partial), and what is missing. For each gap the person asked about:

    * the answer does not say the metric is missing -> the whole sentence (`gap_disclosure`);
    * it says so but does not name what is missing -> the reason (`gap_reason`);
    * it says both -> nothing."""
    sentences: list[str] = []
    for gap in _material_gaps(gaps, question, earlier_question).values():
        if not acknowledges(gap.metric, answer, partial=gap.partial):
            sentences.append(gap_disclosure(gap))
        elif not names_the_need(gap, answer):
            sentences.append(gap_reason(gap))
    return sentences


def add_sentences(answer: str, sentences: Sequence[str]) -> str:
    """`answer` followed by `sentences`, as a short closing paragraph when the answer is already
    several lines, else on the same line."""
    if not sentences:
        return answer
    text = answer.rstrip()
    glue = "\n\n" if "\n" in text else " "
    return text + glue + " ".join(sentences)


def with_disclosures(answer: str, gaps: Sequence[Gap]) -> str:
    """`answer` followed by the whole sentence of each gap."""
    return add_sentences(answer, [gap_disclosure(gap) for gap in gaps])


__all__ = [
    "GAP_METRICS",
    "GapMetric",
    "acknowledges",
    "add_sentences",
    "asked_for",
    "disclosures_for",
    "gap_disclosure",
    "gap_reason",
    "gap_statement",
    "looks_truncated",
    "names_the_need",
    "undisclosed_gaps",
    "with_disclosures",
]
