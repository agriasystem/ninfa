"""Deterministic grounding of the numbers in an answer: the backstop under "no invented facts".

The instructions tell the model to give only figures that appear in the tool observations. This
module CHECKS it, in plain code, for every answer that is about to leave Mia: each number the answer
(or a limitation) states must be one NINFA actually returned this turn - or a calendar date of the
turn, or a date/duration the user themselves named. A number that is none of those is, by
construction, not grounded: it could be an invented figure, a stale figure copied from an earlier
answer in the conversation (history is never a source of facts), a wrong calculation, or a fact
smuggled in by a user message. The turn then fails closed (`UNAVAILABLE`) instead of showing it -
the same posture as the technical-leak and overlength checks (ADR 0026): a wrong number is worse
than an honest "not available".

What a number must be to pass:

* equal to a FIGURE of the observations (`85,00 %` matches `85.00`; `87.840,00` matches
  `87840.00`), or the observation's value rounded to the precision the answer states (`62,08` ->
  `62,1`, `62`). The digits of a date or a time inside an observation ("2026-10-09", "09:31") are
  not figures (`split_observation_numbers`);
* or, ONLY when written as part of a date or a time ("10 ottobre", "sabato 10", "dal 9 al 15
  ottobre", "2026-10-10", "9:31"), a number of the turn's calendar or of the observations' own
  dates: that lets the answer restate a date it was given, and never lends its day numbers to a
  figure ("8 ore" is not grounded just because the 8th of the month is in the calendar, nor "9
  camere libere" because an observation is dated the 9th - that is exactly how a stale or computed
  figure would slip through);
* or a number the user wrote AS A DATE OR A DURATION ("12 ottobre", "il 10", "3 notti"): an answer
  restating the period it is about must not fail. Any OTHER number in the question ("sappi che sono
  pieno al 100%") is a claim, not a fact: it is not grounded by being said, so an answer that echoes
  it fails like an invented one;
* or the 100 of NINFA's confidence scale, written "78 su 100" / "78/100" (the 78 itself must be
  grounded like any figure).

What it deliberately does NOT cover (and the tests/ADR say so): numbers spelled out in words ("tre
camere"), the meaning of a number (a correct number attached to the wrong thing), and qualitative
claims. Those are the model's instructions' job and the real-model smoke test's.
"""

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# A number as it appears in Italian prose: "87.840,00" / "85,50" / "7" / "2.5" (rare).
_ANSWER_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")
# A number in the (machine-written) observation JSON: "85.00", "1100.00", "2026", "08".
_OBSERVATION_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# "1) ..." / "2. ..." at the start of a line is list numbering, not a figure.
_LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
# An identifier (a decision or a conversation id) is a name, never a figure: the digit runs inside a
# UUID must not be able to "ground" a small invented number.
_UUID = re.compile(
    r"(?<![0-9A-Fa-f-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Fa-f-])"
)
# Digits glued to a letter ("COVID19", "B2B") are names, not figures.
_GLUED = re.compile(r"[A-Za-z]\d+|\d+[A-Za-z]{2,}")

_THOUSANDS_GROUP = re.compile(r"^\d{1,3}(?:\.\d{3})+$")

_MONTHS = (
    "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre"
)
# The only shapes in which a number the USER wrote counts as "restating the period asked about".
_USER_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+(?:{_MONTHS})\b", re.IGNORECASE)
_USER_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?\b")
_USER_DURATION = re.compile(
    r"\b(\d{1,3})\s+(?:giorni|giorno|notti|notte|settimane|settimana|mesi|mese)\b", re.IGNORECASE
)
_USER_DAY_OF_MONTH = re.compile(r"\b(?:il|del|dal|al)\s+(\d{1,2})\b", re.IGNORECASE)
_USER_YEAR = re.compile(r"\b(20\d{2})\b")

# Numbers of an ANSWER that are part of a date expression (the only place the calendar may ground).
_WEEKDAYS = (
    "lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|"
    "sabato|domenica"
)
_DATE_CONTEXTS = (
    re.compile(rf"\b(\d{{1,2}})\s+(?:{_MONTHS})\b", re.IGNORECASE),  # 10 ottobre
    re.compile(rf"\b(?:{_WEEKDAYS})\s+(\d{{1,2}})\b", re.IGNORECASE),  # sabato 10
    re.compile(
        rf"\b(\d{{1,2}})\s+(?:al|e|a)\s+\d{{1,2}}\s+(?:{_MONTHS})\b", re.IGNORECASE
    ),  # 9 al 15 ottobre
    re.compile(
        rf"\b(\d{{1,2}})\s*[-\u2013]\s*\d{{1,2}}\s+(?:{_MONTHS})\b", re.IGNORECASE
    ),  # 5-11 ottobre
    re.compile(rf"\b(?:{_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE),  # ottobre 2026
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),  # 2026-10-10
    re.compile(r"\b(\d{1,2}):(\d{2})\b"),  # 9:31
)
# The scale of NINFA's confidence ("78 su 100", "78/100"): the instructions (and Mia Home's shipped
# copy) tell the model to word an affidabilità exactly so, so the 100 is the denominator of a scale,
# not a figure - grounded ONLY in this shape, and only because the numerator before it is checked
# like any other number ("27 su 100" with an invented 27 still fails).
_SCALE_DENOMINATOR = re.compile(r"\d\s*(?:\bsu\b|/)\s*(100)\b", re.IGNORECASE)


def _places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _rounded(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def observation_numbers(texts: Iterable[str]) -> frozenset[Decimal]:
    """Every number written anywhere in the given texts (observations, the turn context), as exact
    Decimals."""
    found: set[Decimal] = set()
    for raw in texts:
        text = _without_identifiers(raw)
        for token in _OBSERVATION_NUMBER.findall(text):
            try:
                found.add(Decimal(token))
            except InvalidOperation:  # pragma: no cover - the regex only yields valid numbers
                continue
    return frozenset(found)


def _without_identifiers(text: str) -> str:
    """The text with every UUID blanked out (same length, so no span moves)."""
    return _UUID.sub(lambda match: " " * len(match.group()), text)


def split_observation_numbers(
    texts: Iterable[str],
) -> tuple[frozenset[Decimal], frozenset[Decimal]]:
    """`(figures, date_numbers)` of the given observation texts. A number that is part of a date or
    a clock time ("2026-10-09", "venerdì 9 ottobre", "09:31") is a DATE number: it may ground a date
    the answer restates, never a figure. Without this split every observation that mentions a date
    would silently ground every small number equal to one of its day/month/minute digits - the
    model's own "40 - 31 = 9 camere libere" included."""
    figures: set[Decimal] = set()
    dates: set[Decimal] = set()
    for raw in texts:
        text = _without_identifiers(raw)
        date_spans = _date_spans(text)
        for match in _OBSERVATION_NUMBER.finditer(text):
            try:
                value = Decimal(match.group())
            except InvalidOperation:  # pragma: no cover - the regex only yields valid numbers
                continue
            (dates if _within(match.span(), date_spans) else figures).add(value)
    return frozenset(figures), frozenset(dates)


def observation_figures(texts: Iterable[str]) -> frozenset[Decimal]:
    """The numbers of the observations that are figures (not part of a date or a time)."""
    return split_observation_numbers(texts)[0]


def observation_date_numbers(texts: Iterable[str]) -> frozenset[Decimal]:
    """The numbers of the observations that are part of a date or a time."""
    return split_observation_numbers(texts)[1]


def user_date_numbers(question: str) -> frozenset[Decimal]:
    """The numbers of the user's own question that are a date or a duration (see the module
    docstring): day of month, month, year, "N giorni/notti/settimane/mesi". A percentage, an amount
    or a count of rooms the user mentions is deliberately NOT here."""
    found: set[Decimal] = set()
    for pattern in (_USER_DAY_MONTH, _USER_DURATION, _USER_DAY_OF_MONTH, _USER_YEAR):
        for match in pattern.finditer(question):
            found.add(Decimal(match.group(1)))
    for match in _USER_NUMERIC_DATE.finditer(question):
        day, month = int(match.group(1)), int(match.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            found.update({Decimal(day), Decimal(month)})
            if match.group(3) is not None:
                found.add(Decimal(match.group(3)))
    return frozenset(found)


def _interpretations(token: str) -> list[Decimal]:
    """The value(s) an Italian-prose number token can mean. "1.100" is one thousand one hundred
    (thousands group) and, rarely, 1.1 - either reading that is grounded is accepted."""
    values: list[Decimal] = []
    candidates: list[str] = []
    if "," in token:
        candidates.append(token.replace(".", "").replace(",", "."))
    elif _THOUSANDS_GROUP.match(token):
        candidates.append(token.replace(".", ""))
        candidates.append(token)
    else:
        candidates.append(token)
    for candidate in candidates:
        try:
            values.append(Decimal(candidate))
        except InvalidOperation:
            continue
    return values


def _is_grounded(value: Decimal, allowed: frozenset[Decimal]) -> bool:
    if value in allowed:
        return True
    places = _places(value)
    return any(
        _places(observed) > places and _rounded(observed, places) == value for observed in allowed
    )


def _date_spans(text: str) -> set[tuple[int, int]]:
    """The spans of the numbers of `text` that belong to a date expression."""
    spans: set[tuple[int, int]] = set()
    for pattern in _DATE_CONTEXTS:
        for match in pattern.finditer(text):
            for group in range(1, (pattern.groups or 0) + 1):
                spans.add(match.span(group))
    return spans


def ungrounded_numbers(
    text: str, allowed: frozenset[Decimal], calendar: frozenset[Decimal] = frozenset()
) -> list[str]:
    """The numbers of `text` that are not grounded, as written, in order. A number is grounded when
    it is in `allowed` (observations, the user's own dates/durations) - or, if it is written as part
    of a date ("10 ottobre"), in `calendar` too. Empty means every figure the text states was
    returned by NINFA, named by the user, or is a date the turn's calendar gave."""
    # Blanking (not deleting) keeps every span aligned with the original text.
    cleaned = _GLUED.sub(lambda m: " " * len(m.group()), text)
    cleaned = _LIST_MARKER.sub(lambda m: " " * len(m.group()), cleaned)
    dated = _date_spans(cleaned)
    scales = {match.span(1) for match in _SCALE_DENOMINATOR.finditer(cleaned)}
    with_calendar = allowed | calendar
    offending: list[str] = []
    for match in _ANSWER_NUMBER.finditer(cleaned):
        token = match.group()
        if match.span() in scales:
            continue
        pool = with_calendar if _within(match.span(), dated) else allowed
        readings = _interpretations(token)
        if not readings or not any(_is_grounded(reading, pool) for reading in readings):
            offending.append(token)
    return offending


def _within(span: tuple[int, int], containers: set[tuple[int, int]]) -> bool:
    start, end = span
    return any(c_start <= start and end <= c_end for c_start, c_end in containers)


__all__ = [
    "observation_date_numbers",
    "observation_figures",
    "observation_numbers",
    "split_observation_numbers",
    "ungrounded_numbers",
    "user_date_numbers",
]
