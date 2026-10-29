"""What every generator of the Universal Understanding Benchmark V2 shares: how a corpus is
assembled from recipes, how values are written, how a header alias is drawn.

The corpus is GENERATED (deterministically: a document depends on its id alone) from recipes,
and the truth of each document is written by the recipe NEXT TO the file it draws - never read
from Smart Import. A recipe draws its headers from vocabularies of what hotels' systems and
hand-made sheets really write; it varies the shape of the document (where the table sits, what
surrounds it, which sheets exist) and the way values are written (dates, amounts, ids), so that
no two documents are a cosmetic copy of each other and none is a document of the official
240-document corpus.

THE TRUTH POLICY (what "READY" means here). A document is READY when a careful person, seeing the
header AND the values AND what surrounds them, would import it without asking anything. A
header that is only a part of a name ("Total", "Importo", "Data") over values that cannot say
more is NOT clear: the recipe says ASK, names the question and gives the answer. Nothing is clear
"because the engine reads it": the engine's vocabulary is deliberately not consulted here.
"""

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from tests.benchmarks.smart_import_v3.draw import Styled
from tests.benchmarks.smart_import_v3.kit import Built, structure_of
from tests.benchmarks.smart_import_v3.model import Doc, Golden
from tests.benchmarks.smart_import_v3.pool import money as pool_money
from tests.benchmarks.smart_import_v3.pool import seeded
from tests.benchmarks.smart_import_v3.pool import when as pool_when

SEED = "universal-understanding-v2"
DIFFICULTIES = ("EASY", "MEDIUM", "HARD", "ADVERSARIAL")
# 120 documents per domain; the negatives are a separate group
COUNTS = {"EASY": 30, "MEDIUM": 40, "HARD": 30, "ADVERSARIAL": 20}

Maker = Callable[[random.Random], Built]

_MONTHS_IT = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def rng_of(case_id: str) -> random.Random:
    return seeded(case_id, seed=SEED)


def assemble(
    prefix: str,
    domain: str,
    recipes: dict[str, Sequence[Maker]],
    counts: dict[str, int] | None = None,
) -> list[Doc]:
    """`counts[difficulty]` documents per difficulty, cycling through that difficulty's recipes."""
    counts = counts or COUNTS
    docs: list[Doc] = []
    number = 0
    for difficulty in DIFFICULTIES:
        makers = recipes[difficulty]
        for k in range(counts[difficulty]):
            number += 1
            maker = makers[k % len(makers)]
            case_id = f"{prefix}{number:03d}_{difficulty.lower()}_{maker.__name__}"
            built = maker(rng_of(case_id))
            docs.append(
                Doc(
                    id=case_id,
                    card=built.card or domain,
                    filename=built.filename,
                    content=built.content,
                    golden=built.golden,
                    tags=(
                        difficulty.lower(),
                        f"recipe:{maker.__name__}",
                        "csv" if built.filename.endswith(".csv") else "xlsx",
                        "unseen",
                    ),
                    structure=structure_of(built),
                    sheet_count=max(1, len(built.sheets)),
                )
            )
    return docs


def without_table(golden: Golden) -> Golden:
    """The truth of a document whose records the product deliberately does not read (a hidden
    sheet): a refusal, with no table to find and no column to map - so no table score at all."""
    return replace(
        golden,
        sheets=(),
        header_rows=(),
        first_row=None,
        data_rows=0,
        skipped={},
        fields={},
        ambiguous=(),
        absent=(),
        unmapped=(),
        labels={},
        questions=(),
        date_order=None,
        decimal=None,
        answers={},
    )


def difficulty_of(doc: Doc) -> str:
    return next(t for t in doc.tags if t in {d.lower() for d in DIFFICULTIES}).upper()


def recipe_of(doc: Doc) -> str:
    return next(t for t in doc.tags if t.startswith("recipe:")).split(":", 1)[1]


# --- dates ----------------------------------------------------------------------------------------


def date_cell(day: date, style: str) -> Any:
    """A date as a document writes it (the official styles, and the ones with a month NAME)."""
    if style == "text_it":
        return f"{day.day} {_MONTHS_IT[day.month - 1]} {day.year}"
    if style == "text_it_long":
        return f"{day.day:02d}-{_MONTHS_IT[day.month - 1]}-{day.year % 100:02d}"
    if style == "text_en":
        return f"{_MONTHS_EN[day.month - 1]} {day.day}, {day.year}"
    if style == "slash_iso":
        return day.strftime("%Y/%m/%d")
    return pool_when(day, style)


# dates whose day number alone can never say the order (unambiguous only when some day > 12)
TEXT_DAY_FIRST = {"it", "dotted", "short", "weekday"}
TEXT_MONTH_FIRST = {"us"}
SELF_EVIDENT = {
    "xl",
    "xl_iso",
    "xl_long",
    "iso",
    "dash_mon",
    "text_it",
    "text_it_long",
    "text_en",
    "slash_iso",
}


def order_of(style: str) -> str | None:
    """The order a TEXT date style is written in (None: a real date, or a style that says it)."""
    if style in TEXT_DAY_FIRST:
        return "DMY"
    if style in TEXT_MONTH_FIRST:
        return "MDY"
    return None


# --- amounts --------------------------------------------------------------------------------------

MONEY_STYLES = (
    "num",
    "num_eur",
    "num_fmt",
    "it",
    "it_plain",
    "us",
    "point",
    "eur_prefix",
    "eur_suffix",
    "eur_prefix_point",
)
DECIMAL_OF = {
    "it": ",",
    "it_plain": ",",
    "eur_prefix": ",",
    "eur_suffix": ",",
    "us": ".",
    "point": ".",
    "eur_prefix_point": ".",
}


def money_cell(value: float, style: str) -> Any:
    if style == "space_it":  # 1 234,50
        whole, _, cents = f"{value:,.2f}".replace(",", " ").partition(".")
        return f"{whole},{cents}"
    if style == "eur_code":  # EUR 1234.50
        return f"EUR {value:.2f}"
    return pool_money(value, style)


def decimal_of(style: str) -> str | None:
    if style == "space_it":
        return ","
    if style == "eur_code":
        return "."
    return DECIMAL_OF.get(style)


# --- numbers --------------------------------------------------------------------------------------


def number_cell(value: int | float, style: str) -> Any:
    """An integer / count as text or number."""
    if style == "text":
        return str(value)
    return value


def number_of(rng: random.Random, low: int, high: int) -> int:
    return rng.randint(low, high)


# --- aliases --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class H:
    """A header as a system or a person writes it. `lang` is the language of the document it fits
    (`any`: both)."""

    text: str
    lang: str = "any"


def pick(rng: random.Random, options: Sequence[H], lang: str) -> str:
    fitting = [o for o in options if o.lang in {"any", lang}]
    return rng.choice(fitting).text


def pick_language(rng: random.Random) -> str:
    return rng.choice(("it", "it", "en"))


def maybe(rng: random.Random, probability: float) -> bool:
    return rng.random() < probability


def styled_text(value: str) -> Styled:
    """A string that must stay a string even if it looks like a number or a formula."""
    return Styled(value, text=True)


def day_of(base: date, offset: int) -> date:
    return date.fromordinal(base.toordinal() + offset)


def stamp_cell(moment: datetime, style: str) -> Any:
    if style == "xl":
        return moment
    if style == "iso":
        return moment.strftime("%Y-%m-%d %H:%M")
    if style == "it":
        return moment.strftime("%d/%m/%Y %H:%M")
    return date_cell(moment.date(), style)


def count_by(items: Sequence[Any], key: Callable[[Any], str]) -> dict[str, int]:
    return dict(Counter(key(item) for item in items))
