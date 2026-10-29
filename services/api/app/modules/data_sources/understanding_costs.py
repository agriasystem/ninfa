"""What a cost register needs beyond its columns: which amount is NET, and what the categories mean.

NINFA's cost analysis works with the NET amount (before VAT). A register may say so ("Imponibile"),
or give an "Importo" / "Totale" that does not. Three things settle it, in this order, and none of
them is a guess:

    1. the header says it is net (imponibile, netto, ...)                         -> sure
    2. net + VAT = total on the rows of the file (the three columns confirm
       each other)                                                                -> sure
    3. nothing says it                                                            -> ONE question;
       "no, it includes VAT" is a plain "this cannot be imported as it is" (the net amount of a
       line is not NINFA's to work out)

The category words are NINFA's own lexicon plus what the hotel taught; a word it does not know is
asked about once, never mapped to OTHER on its own.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final, Literal

from app.modules.bookings.text import normalize_key
from app.modules.data_sources.proposal import CONTESTED, ColumnProposal, Proposal
from app.modules.data_sources.semantics import Level, NameMatch
from app.modules.data_sources.semantics_costs import GROSS_WORDS, NET_WORDS
from app.modules.data_sources.understanding_types import (
    Blocker,
    BlockerCode,
    Choice,
    LabelCount,
    OriginKind,
    Question,
    QuestionKind,
)
from app.modules.document_understanding.structure import as_decimal
from app.modules.document_understanding.text import fold, tokens
from app.modules.document_understanding.values import text_of
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.mapping import resolve_category

MAX_LABELS_ASKED = 12
# Rows read to check that net + VAT = total (a register can be long: the evidence is what matters).
_COHERENCE_ROWS = 400
_COHERENT = 0.9
_PENNY = Decimal("0.02")

# NINFA's own words for the cost categories, by their comparison key. Deliberately small: a word
# that could mean two categories is not here ("Food & Beverage" is food OR beverage, "Forniture" is
# amenities, cleaning or food: those are asked once, and remembered).
_LEXICON: Final[dict[CostCategory, tuple[str, ...]]] = {
    CostCategory.PERSONNEL: ("personale", "stipendi", "salari", "dipendenti", "payroll", "staff"),
    CostCategory.LAUNDRY: ("lavanderia", "laundry", "biancheria"),
    CostCategory.CLEANING: ("pulizie", "pulizia", "cleaning", "housekeeping", "detersivi"),
    CostCategory.AMENITIES: ("amenities", "cortesia", "articoli di cortesia", "cortesie"),
    CostCategory.FOOD: (
        "alimentari",
        "cibo",
        "food",
        "derrate",
        "generi alimentari",
        "colazioni",
        "colazione",
        "prima colazione",
        "breakfast",
        "ristorazione",
    ),
    CostCategory.BEVERAGE: ("bevande", "beverage", "beverages", "vini"),
    CostCategory.UTILITIES: (
        "utenze",
        "energia",
        "elettricita",
        "luce",
        "gas",
        "acqua",
        "utilities",
        "energia elettrica",
        "riscaldamento",
        "metano",
    ),
    CostCategory.MAINTENANCE: ("manutenzione", "manutenzioni", "riparazioni", "maintenance"),
    CostCategory.SOFTWARE: ("software", "licenze software", "saas", "abbonamenti software"),
    CostCategory.MARKETING: ("marketing", "pubblicita", "advertising", "promozione"),
    CostCategory.OTA_COMMISSIONS: (
        "commissioni ota",
        "commissioni",
        "ota commissions",
        "commissioni booking",
        "commissioni booking com",
        "commissioni expedia",
    ),
    CostCategory.PROFESSIONAL_SERVICES: (
        "consulenze",
        "consulenza",
        "servizi professionali",
        "professionisti",
        "professional services",
    ),
    CostCategory.TRANSPORT: ("trasporti", "trasporto", "transport", "carburante"),
    CostCategory.OTHER: ("altro", "other", "varie", "diversi", "misc"),
}
_BY_WORD: Final[dict[str, CostCategory]] = {
    normalize_key(word): category for category, words in _LEXICON.items() for word in words
}

AmountsCheck = Literal["MATCH", "MISMATCH"]


def category_of(label: str, taught: Mapping[str, str]) -> CostCategory | None:
    """The category a word in a register means, by what the hotel taught, a NINFA category name or
    NINFA's own lexicon; None when it is none of those."""
    key = normalize_key(label)
    if key in taught:
        try:
            return CostCategory(taught[key])
        except ValueError:
            return None
    named = resolve_category(label, {})
    if named is not None:
        return named
    return _BY_WORD.get(key)


def lexicon_labels(labels: Sequence[tuple[str, int]], taught: Mapping[str, str]) -> dict[str, str]:
    """The words NINFA recognises by its OWN lexicon (not taught, not a category name): they travel
    in the decision so the import, which only reads canonical names and confirmed words, knows
    them too."""
    found: dict[str, str] = {}
    for label, _count in labels:
        key = normalize_key(label)
        if key in taught or resolve_category(label, {}) is not None:
            continue
        category = _BY_WORD.get(key)
        if category is not None:
            found[label] = category.value
    return found


def category_question(
    labels: Sequence[tuple[str, int]], taught: Mapping[str, str]
) -> Question | None:
    """ONE question about the category words NINFA does not know (the most frequent first)."""
    unknown = [(label, count) for label, count in labels if category_of(label, taught) is None]
    if not unknown:
        return None
    unknown.sort(key=lambda item: (-item[1], item[0]))
    return Question(
        id="LABELS:category_mapping",
        kind=QuestionKind.VALUE_LABELS,
        document="category_mapping",
        field="cost_category",
        choices=tuple(Choice(category.value) for category in CostCategory),
        labels=tuple(LabelCount(label, count) for label, count in unknown[:MAX_LABELS_ASKED]),
        total_labels=len(unknown),
    )


@dataclass(frozen=True, slots=True)
class CostsPlan:
    questions: tuple[Question, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    # header -> field: what the person's answer (or the coherence of the amounts) settled.
    assigned: Mapping[str, str] | None = None
    # Headers whose meaning the rows of the file confirm (net + VAT = total).
    confirmed: frozenset[str] = frozenset()
    amounts: AmountsCheck | None = None


def _says_net(column: ColumnProposal) -> bool:
    """The header itself says the amount is net: a word for it, or a name NINFA knows."""
    return column.name == NameMatch.EXACT or bool(tokens(column.header) & NET_WORDS)


def _says_gross(column: ColumnProposal) -> bool:
    """The header itself says the amount includes VAT ("Totale IVA inclusa", "Importo lordo")."""
    return bool(tokens(column.header) & GROSS_WORDS)


def _decimals(rows: Sequence[Sequence[object]], position: int) -> list[Decimal | None]:
    return [as_decimal(row[position]) if position < len(row) else None for row in rows]  # type: ignore[arg-type]


def amounts_check(
    rows: Sequence[Sequence[object]], net: int, tax: int, gross: int
) -> AmountsCheck | None:
    """Do net + VAT = total on the rows? MATCH needs most rows to add up (a register has the odd
    typo); too few comparable rows prove nothing."""
    nets, taxes, grosses = _decimals(rows, net), _decimals(rows, tax), _decimals(rows, gross)
    compared = ok = 0
    for a, b, c in zip(nets, taxes, grosses, strict=False):
        if a is None or b is None or c is None:
            continue
        compared += 1
        if abs(a + b - c) <= _PENNY:
            ok += 1
    if compared < 3:
        return None
    return "MATCH" if ok / compared >= _COHERENT else "MISMATCH"


def _register_net(proposal: Proposal, rows: Sequence[Sequence[object]]) -> ColumnProposal | None:
    """ "Netto fattura" in a register where EVERY row is a different invoice: the net of the invoice
    is the net of its only line. (When an invoice number comes back on several rows, the same net
    repeated on each of them is the invoice's and not the line's: nothing is decided then.)"""
    assigned = proposal.assigned()
    invoice_net, number = assigned.get("invoice_net_amount"), assigned.get("invoice_number")
    if "line_total" in assigned or invoice_net is None or number is None:
        return None
    numbers = [
        fold(text_of(row[number.position]))  # type: ignore[arg-type]
        for row in rows
        if number.position < len(row)
    ]
    numbers = [n for n in numbers if n]
    if len(numbers) < 3 or len(set(numbers)) / len(numbers) < 0.98:
        return None
    return invoice_net


def plan_costs(
    *,
    proposal: Proposal,
    rows: Sequence[Sequence[object]],
    asked_basis: str | None,
    asked_columns: Mapping[str, str],
) -> CostsPlan:
    """Which column is the NET amount, and what is left to ask about it."""
    register = _register_net(proposal, rows)
    plan = _plan_costs(
        proposal=proposal,
        rows=rows,
        asked_basis=asked_basis,
        asked_columns=asked_columns,
        net=register or proposal.assigned().get("line_total"),
    )
    if register is None:
        return plan
    return replace(plan, assigned={**(plan.assigned or {}), register.header: "line_total"})


def _plan_costs(
    *,
    proposal: Proposal,
    rows: Sequence[Sequence[object]],
    asked_basis: str | None,
    asked_columns: Mapping[str, str],
    net: ColumnProposal | None,
) -> CostsPlan:
    assigned = proposal.assigned()
    gross = assigned.get("invoice_gross_amount")
    tax = assigned.get("invoice_tax_amount")

    # the person already named the net column: nothing to ask
    if "line_total" in asked_columns.values():
        return CostsPlan()
    # two columns say "net" in the same words (an original and an adjusted net, one per VAT rate):
    # which one counts - or whether any single one does - is not a yes/no about a column
    if any(
        c.ambiguous_group == CONTESTED and "line_total" in c.ambiguous_fields
        for c in proposal.columns
    ):
        return CostsPlan()

    check: AmountsCheck | None = None
    confirmed: set[str] = set()
    if net is not None and tax is not None and gross is not None:
        check = amounts_check(rows, net.position, tax.position, gross.position)
        if check == "MATCH":
            confirmed.update({net.header, tax.header, gross.header})
            return CostsPlan(confirmed=frozenset(confirmed), amounts=check)
    if net is not None and _says_net(net):
        return CostsPlan(amounts=check)

    # nothing says the amount is net: ask, or stop if the person says it includes VAT
    bare = net if net is not None else gross
    if bare is None:
        return CostsPlan(amounts=check)  # no amount at all: the required-field check says so
    if asked_basis == "GROSS" or (asked_basis is None and _says_gross(bare)):
        # (said by the person, or written in the header: either way it is not asked)
        return CostsPlan(blockers=(Blocker(BlockerCode.AMOUNT_NOT_NET),), amounts=check)
    if asked_basis == "NET":
        return CostsPlan(assigned={bare.header: "line_total"}, amounts=check)
    question = Question(
        id="AMOUNT_BASIS",
        kind=QuestionKind.AMOUNT_BASIS,
        column=bare.header,
        field="line_total",
        origin=OriginKind.COLUMN,
        choices=(Choice("NET"), Choice("GROSS")),
    )
    return CostsPlan(questions=(question,), amounts=check)


def promote(proposal: Proposal, headers: frozenset[str]) -> Proposal:
    """The columns the rows of the file confirm are as sure as a name that says it."""
    return Proposal(
        tuple(
            replace(c, level=Level.HIGH) if c.header in headers and c.field is not None else c
            for c in proposal.columns
        )
    )


__all__ = [
    "AmountsCheck",
    "CostsPlan",
    "amounts_check",
    "category_of",
    "category_question",
    "lexicon_labels",
    "plan_costs",
    "promote",
]
