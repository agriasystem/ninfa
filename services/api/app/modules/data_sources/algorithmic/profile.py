"""What the values of ONE column look like: a structured, deterministic profile.

The V3 `ColumnStats` answer "what kind of cells are these" (counts and a few distinct texts). A
profile adds what a person sees at a glance and the matcher needs to tell two fields apart: how much
is empty, how unique the values are, whether they are whole numbers or have cents, their sign and
range, how long the texts are, which few words repeat, whether they are written as money, as
percentages or as identifiers, and what share of them are words NINFA knows (a booking status, a
sales channel, a department, a currency, a cost category).

PRIVACY. A profile is computed in memory from the rows the caller already read and kept nowhere.
Its `top_values` are only ever filled for a column of repeating WORDS that is not personal data
(a status, a channel, a department): never for names, contacts, identifiers or free text, and never
longer than `TOP_VALUE_CHARS`. Nothing here is logged, and `describe()` (the debug view) prints
only counts and shapes.
"""

import re
import weakref
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock

from app.modules.bookings.parsers import Cell
from app.modules.bookings.statuses import BUILTIN_STATUS_KEYS
from app.modules.bookings.text import normalize_key
from app.modules.data_sources.algorithmic.header import Header, normalize
from app.modules.data_sources.channel_words import channel_share, is_place
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.semantics import fit_currency
from app.modules.data_sources.understanding_costs import category_of
from app.modules.data_sources.understanding_labor import names_a_department
from app.modules.document_understanding.pii import PiiKind
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.structure import as_decimal
from app.modules.document_understanding.values import CellKind, kind_of
from app.modules.ingestion.value_text import (
    month_name_date,
    split_weekday,
    strip_currency,
    strip_hours_unit,
)

MAX_TOP_VALUES = 8
TOP_VALUE_CHARS = 24
NUMERIC_ID_FROM = 10_000_000
# A column of words repeats: only then are its commonest values worth keeping
_CATEGORICAL_DISTINCT = 40

# more words a booking can be in than NINFA's importer maps: only for READING a column (a column
# of these is a status), never for importing it (an unknown label is asked about by the importer)
_STATUS_WORDS = frozenset(
    normalize_key(word)
    for word in (
        "booked",
        "reserved",
        "tentative",
        "pending",
        "provisional",
        "option",
        "optioned",
        "waitlist",
        "waiting list",
        "in house",
        "inhouse",
        "in-house",
        "arrived",
        "departed",
        "completed",
        "closed",
        "checkin",
        "checkout",
        "check in",
        "check out",
        "checked-in",
        "checked-out",
        "confirmed",
        "cancelled",
        "canceled",
        "no show",
        "noshow",
        "no-show",
        "prenotata",
        "prenotato",
        "in attesa",
        "opzione",
        "opzionata",
        "provvisoria",
        "provvisorio",
        "in casa",
        "arrivato",
        "arrivata",
        "partito",
        "partita",
        "completata",
        "completato",
        "chiusa",
        "chiuso",
        "confermata",
        "confermato",
        "cancellata",
        "cancellato",
        "annullata",
        "annullato",
        "non presentato",
        "non presentata",
        "no show",
    )
) | frozenset(BUILTIN_STATUS_KEYS)

_SHAPE_DIGIT = re.compile(r"\d")
_SHAPE_UPPER = re.compile(r"[A-Z]")
_SHAPE_LOWER = re.compile(r"[a-z]")
_IDENTIFIER = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9._/\-]{2,23}$")
_CURRENCY_MARK = re.compile(r"(€|\$|£|\beur\b|\busd\b|\bgbp\b)", re.IGNORECASE)
_PERCENT = re.compile(r"%")
_THOUSANDS = re.compile(r"\d[.,' ]\d{3}(?:\D|$)")


class Primitive(StrEnum):
    EMPTY = "EMPTY"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    TIME = "TIME"
    TEXT = "TEXT"
    MIXED = "MIXED"


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    position: int
    raw_header: str
    header: Header
    rows: int  # rows read (empty ones included)
    non_null: int
    null_rate: float
    unique: int
    uniqueness: float  # unique / non-null
    primitive: Primitive
    numeric_share: float
    date_share: float
    text_share: float
    minimum: Decimal | None
    maximum: Decimal | None
    positive: int
    negative: int
    zero: int
    integer_share: float  # of the numbers, how many have no decimals
    cents_share: float  # of the numbers, how many are written with exactly two decimals
    date_min: date | None
    date_max: date | None
    length_min: int
    length_mean: float
    length_max: int
    top_values: tuple[tuple[str, int], ...]
    money_like: float  # share written as an amount (a currency mark, thousands, cents)
    percent_like: float  # share written with a % sign
    identifier_like: float  # share that look like a code: letters/digits, with a digit, no spaces
    shape_consistency: float  # share of values with the commonest "shape" (AA999, 9999/99)
    # of the distinct text values, the share that is a word NINFA knows
    status_share: float
    channel_share: float
    place_share: float
    department_share: float
    currency_share: float
    category_share: float
    personal: bool  # the column is personal data: nothing of it is ever kept or shown

    def describe(self) -> dict[str, object]:
        """Counts and shapes only - safe for a log or a report."""
        return {
            "header": self.header.text,
            "primitive": self.primitive.value,
            "non_null": self.non_null,
            "null_rate": round(self.null_rate, 3),
            "uniqueness": round(self.uniqueness, 3),
            "numeric": round(self.numeric_share, 3),
            "date": round(self.date_share, 3),
            "text": round(self.text_share, 3),
            "integer": round(self.integer_share, 3),
            "cents": round(self.cents_share, 3),
            "negative": self.negative,
            "identifier_like": round(self.identifier_like, 3),
            "shape": round(self.shape_consistency, 3),
            "status": round(self.status_share, 3),
            "channel": round(self.channel_share, 3),
            "department": round(self.department_share, 3),
            "currency": round(self.currency_share, 3),
            "category": round(self.category_share, 3),
            "money_like": round(self.money_like, 3),
            "percent_like": round(self.percent_like, 3),
        }


def _share(count: int, whole: int) -> float:
    return count / whole if whole else 0.0


def _shape(text: str) -> str:
    out = _SHAPE_DIGIT.sub("9", text)
    out = _SHAPE_UPPER.sub("A", out)
    return _SHAPE_LOWER.sub("a", out)


def _day(cell: Cell) -> date | None:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if isinstance(cell, str):
        text = split_weekday(cell.strip())[0]
        named = month_name_date(text)
        if named is not None:
            return named.date()
        head = text[:10]
        for separator in ("-", "/", "."):
            parts = head.split(separator)
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                a, b, c = (int(part) for part in parts)
                try:
                    if len(parts[0]) == 4:
                        return date(a, b, c)
                    if len(parts[2]) == 4:
                        return date(c, b, a) if a > 12 or b <= 12 else date(c, a, b)
                except ValueError:
                    return None
    return None


def _decimals(text: str) -> int | None:
    """How many decimals a written number has (None: no decimal mark that says so)."""
    cleaned = strip_hours_unit(strip_currency(text)).replace(" ", "").replace(" ", "")
    cleaned = cleaned.rstrip("%€$£").strip()
    last = max(cleaned.rfind(","), cleaned.rfind("."))
    if last < 0:
        return 0
    tail = cleaned[last + 1 :]
    return len(tail) if tail.isdigit() and len(tail) != 3 else None


# One upload is understood several times (once per kind of data, to say which it is, then once for
# the kind chosen) over the SAME column samples: a profile does not depend on the kind of data, so
# it
# is computed once per sample. The cache holds NO reference to the sample (a weak one only): when
# the request is over and the sample is collected, its entry goes with it, so nothing of a
# customer's
# file outlives the request, and a profile itself holds counts, shapes and a few vocabulary words.
_cache: dict[tuple[int, bool], tuple[weakref.ReferenceType[ColumnSample], ColumnProfile]] = {}
_cache_lock = Lock()


def profile_column(
    sample: ColumnSample, stats: ColumnStats, *, pii: PiiKind | None = None, locked: bool = False
) -> ColumnProfile:
    """The profile of one column (cached per sample: see above)."""
    personal = locked or pii is not None
    key = (id(sample), personal)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0]() is sample:
            return hit[1]
    profile = _profile(sample, stats, personal)

    def forget(_reference: object, key: tuple[int, bool] = key) -> None:
        with _cache_lock:
            _cache.pop(key, None)

    with _cache_lock:
        _cache[key] = (weakref.ref(sample, forget), profile)
    return profile


def _profile(sample: ColumnSample, stats: ColumnStats, personal: bool) -> ColumnProfile:
    values = sample.values
    rows = len(sample.rows) if sample.rows else len(values)
    n = stats.n
    kinds = {kind: stats.kinds.get(kind, 0) for kind in CellKind}
    # ONE pass over the cells: what kind each is, and the three lists the rest needs
    numeric: list[Cell] = []
    text_cells: list[str] = []
    dated: list[Cell] = []
    for cell in values:
        kind = kind_of(cell)
        if kind == CellKind.NUMBER:
            numeric.append(cell)
        elif kind == CellKind.DATE:
            dated.append(cell)
        elif kind == CellKind.TEXT and isinstance(cell, str):
            text_cells.append(cell.strip())
    numbers = [number for cell in numeric if (number := as_decimal(cell)) is not None]

    positive = sum(1 for number in numbers if number > 0)
    negative = sum(1 for number in numbers if number < 0)
    zero = len(numbers) - positive - negative
    integer = sum(1 for number in numbers if number == number.to_integral_value())

    cents = written = 0
    money = percent = 0
    for cell in numeric:
        if isinstance(cell, str):
            written += 1
            places = _decimals(cell)
            cents += 1 if places == 2 else 0
            if _CURRENCY_MARK.search(cell) or _THOUSANDS.search(cell):
                money += 1
            if _PERCENT.search(cell):
                percent += 1
        elif isinstance(cell, float) and not cell.is_integer():
            written += 1
            cents += 1 if round(cell, 2) == cell else 0
    cents_share = _share(cents, written)

    days = [day for cell in dated if (day := _day(cell))]

    lengths = [len(text) for text in text_cells]
    identifier = sum(1 for text in text_cells if _IDENTIFIER.match(text))
    # identifiers written as numbers (4800000123): whole and LONG - an amount of a hotel never
    # reaches eight digits, a booking number often does (shorter ones are told by their header)
    numeric_ids = (
        sum(1 for number in numbers if abs(number) >= NUMERIC_ID_FROM)
        if numbers and integer == len(numbers)
        else 0
    )
    shapes = Counter(_shape(text) for text in text_cells)
    shape_consistency = _share(shapes.most_common(1)[0][1], len(text_cells)) if shapes else 0.0

    distinct_texts = list(stats.texts)
    categorical = (
        not personal
        and bool(distinct_texts)
        and stats.text_fraction >= 0.8
        and 0 < stats.distinct <= _CATEGORICAL_DISTINCT
    )
    top: tuple[tuple[str, int], ...] = ()
    if categorical:
        counts = Counter(text.strip() for text in text_cells)
        top = tuple(
            (value[:TOP_VALUE_CHARS], count)
            for value, count in counts.most_common(MAX_TOP_VALUES)
            if len(value) <= TOP_VALUE_CHARS
        )

    known = len(distinct_texts)

    def word_share(check: Callable[[str], bool]) -> float:
        if not known:
            return 0.0
        return sum(1 for text in distinct_texts if check(text)) / known

    if kinds[CellKind.DATE] == n and n:
        primitive = Primitive.DATE
    elif kinds[CellKind.TIME] == n and n:
        primitive = Primitive.TIME
    elif n == 0:
        primitive = Primitive.EMPTY
    elif stats.numeric == n:
        primitive = Primitive.INTEGER if integer == len(numbers) else Primitive.DECIMAL
    elif stats.text_fraction >= 0.95:
        primitive = Primitive.TEXT
    else:
        primitive = Primitive.MIXED

    return ColumnProfile(
        position=sample.position,
        raw_header=sample.header,
        header=normalize(sample.header),
        rows=rows,
        non_null=n,
        null_rate=1.0 - _share(n, rows) if rows else 0.0,
        unique=stats.distinct,
        uniqueness=stats.distinct_ratio,
        primitive=primitive,
        numeric_share=stats.numeric_fraction,
        date_share=stats.date_fraction,
        text_share=stats.text_fraction,
        minimum=stats.minimum,
        maximum=stats.maximum,
        positive=positive,
        negative=negative,
        zero=zero,
        integer_share=_share(integer, len(numbers)),
        cents_share=cents_share,
        date_min=min(days) if days else None,
        date_max=max(days) if days else None,
        length_min=min(lengths) if lengths else 0,
        length_mean=sum(lengths) / len(lengths) if lengths else 0.0,
        length_max=max(lengths) if lengths else 0,
        top_values=top,
        money_like=_share(money, written),
        percent_like=_share(percent, written),
        identifier_like=max(
            _share(identifier, len(text_cells)) if text_cells else 0.0,
            _share(numeric_ids, len(numbers)),
        ),
        shape_consistency=shape_consistency,
        status_share=word_share(lambda text: normalize_key(text) in _STATUS_WORDS),
        channel_share=channel_share(distinct_texts) if distinct_texts else 0.0,
        place_share=word_share(is_place),
        department_share=word_share(names_a_department),
        currency_share=fit_currency(stats) if distinct_texts else 0.0,
        category_share=word_share(lambda text: category_of(text, {}) is not None),
        personal=personal,
    )


__all__ = ["MAX_TOP_VALUES", "TOP_VALUE_CHARS", "ColumnProfile", "Primitive", "profile_column"]
