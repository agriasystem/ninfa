"""Documents for the capabilities of Gate 2.1, so that they are measured on unseen files too.

The official corpus has ONE document for each of them (`LO07`, `CO04`, `BO09`). A rule proven on one
document proves nothing about the next, and the dev / holdout split needs documents to split. These
30 documents give each capability its variety - and its counter-examples:

  stated_department      "Reparto: Spa" (8 spellings of the label, two languages) over a table with
                         no department column: the department of every row, no question
  other_label            the same word after "Nota:", "Cliente:", "Responsabile:", "Fornitore:": NOT
                         a department, so the department is asked
  document_and_booking   a register with the date of the document and the date it was registered:
                         one invoice date, no question
  rival_dates            two dates that both say "invoice": a real choice
  status_codes           a status written in the hotel's own letters: asked once, as words

The truth is written beside the file, as everywhere in V2, and never read from the engine.
"""

import random
from dataclasses import replace
from typing import Any

from tests.benchmarks.smart_import_v3.cols import Col
from tests.benchmarks.smart_import_v3.kit import Built, structure_of
from tests.benchmarks.smart_import_v3.model import TITLE, Doc
from tests.benchmarks.universal_understanding_v2 import gen_bookings as bookings
from tests.benchmarks.universal_understanding_v2 import gen_costs as costs
from tests.benchmarks.universal_understanding_v2 import gen_labor as labor
from tests.benchmarks.universal_understanding_v2.common import date_cell, pick, rng_of

# single words every hotel writes the same way (the label is what is being tested, not the word)
DEPARTMENTS = {
    "it": (
        "Reception",
        "Housekeeping",
        "Cucina",
        "Sala",
        "Bar",
        "Manutenzione",
        "Spa",
        "Direzione",
    ),
    "en": ("Reception", "Housekeeping", "Kitchen", "Bar", "Maintenance", "Spa", "Management"),
}
DEPARTMENT_LABELS = {
    "it": ("Reparto:", "Settore:", "Area:", "Dipartimento:"),
    "en": ("Department:", "Dept:", "Team:", "Area:"),
}
# (label, how a value about a note / a customer / a person / a supplier is written)
OTHER_LABELS = {
    "it": (
        ("Nota:", "{d} chiusa lunedi"),
        ("Cliente:", "{d} S.r.l."),
        ("Responsabile:", "{d}"),
        ("Fornitore:", "{d} Service S.r.l."),
    ),
    "en": (
        ("Note:", "{d} closed on Monday"),
        ("Customer:", "{d} Ltd"),
        ("Manager:", "{d}"),
        ("Supplier:", "{d} Services Ltd"),
    ),
}
DATE_PAIRS = (
    ("it", "Data doc.", "Data reg."),
    ("it", "Data documento", "Data registrazione"),
    ("it", "Data fattura", "Data reg."),
    ("it", "Data doc.", "Data registrazione"),
    ("en", "Document date", "Registration date"),
    ("en", "Invoice date", "Registration date"),
)
RIVAL_PAIRS = (("it", "Data fattura", "Data emissione"), ("en", "Invoice date", "Issue date"))
STATUS_CODES = (
    ("OK", "CANC", "NS"),
    ("K", "X", "N"),
    ("A", "C", "S"),
    ("OK", "ANN", "NSH"),
)
STATUS_OF = ("CONFIRMED", "CANCELLED", "NO_SHOW")


def stated_department(rng: random.Random) -> Built:
    style = labor.pick_style(rng)
    lang = style.lang
    dept = rng.choice(DEPARTMENTS[lang])
    days = labor.period(rng, rng.randint(4, 7))
    shifts = labor.roster(rng, people=rng.randint(3, 4), days=days, depts=[dept])
    cols = [c for c in labor.core_cols(rng, style) if c.field != "department"]
    cols.insert(1, labor.person_col(rng, lang))
    block: list[Any] = [("label", rng.choice(DEPARTMENT_LABELS[lang]), dept)]
    period = labor.period_text(rng, lang, days[0], days[-1])
    others = [
        ("label", "Periodo:" if lang == "it" else "Period:", period),
        ("label", "Struttura:" if lang == "it" else "Property:", rng.choice(labor.HOTELS)),
        ("label", "Responsabile:" if lang == "it" else "Manager:", rng.choice(DEPARTMENTS[lang])),
    ]
    block += rng.sample(others, rng.randint(1, 3))
    rng.shuffle(block)
    return labor.document(
        rng,
        cols,
        shifts,
        style,
        name=f"turni_{dept.lower()}.xlsx" if lang == "it" else f"roster_{dept.lower()}.xlsx",
        preamble=block,
        extra_fields={"department": TITLE},
        note="The department is stated by a label that says so: the rows are its rows.",
    )


def other_label(rng: random.Random) -> Built:
    style = labor.pick_style(rng)
    lang = style.lang
    dept = rng.choice(DEPARTMENTS[lang])
    days = labor.period(rng, rng.randint(4, 7))
    shifts = labor.roster(rng, people=rng.randint(3, 4), days=days, depts=[dept])
    cols = [c for c in labor.core_cols(rng, style) if c.field != "department"]
    cols.insert(1, labor.person_col(rng, lang))
    label, value = rng.choice(OTHER_LABELS[lang])
    block: list[Any] = [("label", label, value.format(d=dept))]
    block.append(("label", "Periodo:" if lang == "it" else "Period:", "2026"))
    return labor.document(
        rng,
        cols,
        shifts,
        style,
        name="turni_senza_reparto.xlsx" if lang == "it" else "roster_no_department.xlsx",
        outcome="ASK",
        preamble=block,
        questions=("DEPARTMENT_ROWS",),
        answers={"department_value": labor.CATEGORY_OF[dept]},
        note=f"'{label} {value.format(d=dept)}' is not the department of the rows: nobody says it.",
    )


def _register(rng: random.Random, pair: tuple[str, str, str], *, rival: bool) -> Built:
    lang, first, second = pair
    look = costs.pick_look(rng, lang=lang)
    items = costs.bills(rng, rng.randint(10, 18), lang=lang)
    document_date = Col(
        first,
        lambda b: date_cell(b.day, look.dates),
        "invoice_date",
        ambiguous=rival,
    )
    other_date = Col(
        second,
        lambda b: date_cell(b.day if rival else b.booked, look.dates),
        "invoice_date" if rival else None,
        ambiguous=rival,
    )
    cols = [
        costs.c_supplier(rng, look),
        costs.c_number(rng, look),
        costs.c_desc(rng, look),
        document_date,
        other_date,
        *costs.amounts(rng, look, "net"),
    ]
    if rng.random() < 0.5:
        cols[3], cols[4] = cols[4], cols[3]  # (the registration date may come first)
    name = "registro_acquisti.xlsx" if lang == "it" else "purchase_ledger.xlsx"
    if not rival:
        return costs.document(
            rng,
            cols,
            items,
            look,
            name=name,
            note="The date of the document is the invoice date; the date it was registered is not.",
        )
    return costs.document(
        rng,
        cols,
        items,
        look,
        name=name,
        outcome="NOT_AUTOMATIC",
        tolerated=("COLUMN_MEANING",),
        note="Two dates that both say 'invoice': which one is a choice.",
    )


def document_and_registration(rng: random.Random) -> Built:
    return _register(rng, rng.choice(DATE_PAIRS), rival=False)


def rival_dates(rng: random.Random) -> Built:
    return _register(rng, rng.choice(RIVAL_PAIRS), rival=True)


def status_codes(rng: random.Random) -> Built:
    style = bookings.pick_style(rng)
    items = bookings.stays(rng, rng.randint(12, 20), statuses=STATUS_OF)
    for index, status in enumerate(STATUS_OF):  # (every status appears at least once)
        items[index] = replace(items[index], status=status)
    codes = dict(zip(STATUS_OF, rng.choice(STATUS_CODES), strict=True))
    header = pick(rng, bookings.STATUS_H, style.lang)
    cols = bookings.core(rng, style, status=False)
    cols.append(Col(header, lambda s: codes[s.status], "status"))
    meaning = {code: status for status, code in codes.items()}
    return bookings.document(
        rng,
        cols,
        items,
        style,
        name="prenotazioni_stati.xlsx" if style.lang == "it" else "bookings_status_codes.xlsx",
        outcome="ASK",
        labels={"status_mapping": dict.fromkeys(meaning, "?")},
        questions=("VALUE_LABELS",),
        answers={"labels": {"status_mapping": meaning}},
        note="The status is written in the hotel's own letters: asked once, as words.",
    )


RECIPES: tuple[tuple[str, int, str, Any], ...] = (
    ("stated_department", 8, "MEDIUM", stated_department),
    ("other_label", 4, "ADVERSARIAL", other_label),
    ("document_and_registration", 8, "MEDIUM", document_and_registration),
    ("rival_dates", 2, "ADVERSARIAL", rival_dates),
    ("status_codes", 8, "MEDIUM", status_codes),
)


def build() -> list[Doc]:
    docs: list[Doc] = []
    number = 0
    for name, count, difficulty, maker in RECIPES:
        for _ in range(count):
            number += 1
            case_id = f"UK{number:03d}_{difficulty.lower()}_{name}"
            built = maker(rng_of(case_id))
            docs.append(
                Doc(
                    id=case_id,
                    card=built.card or built.golden.domain,
                    filename=built.filename,
                    content=built.content,
                    golden=built.golden,
                    tags=(
                        difficulty.lower(),
                        f"recipe:{name}",
                        "csv" if built.filename.endswith(".csv") else "xlsx",
                        "unseen",
                    ),
                    structure=structure_of(built),
                    sheet_count=max(1, len(built.sheets)),
                )
            )
    return docs


__all__ = ["RECIPES", "build"]
