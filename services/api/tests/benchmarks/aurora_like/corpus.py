"""Files shaped like a real hotel's bookings export: title rows, a counter above the table, guest
contacts, notes, a summary sheet. Synthetic: no name, phone or address here belongs to anyone.

The truth of each case was written before running the engine on it, from one question: if NINFA
decided this file alone, could it be wrong about what is on the books? Nothing here is a hand-picked
regression of a known file: the variants move what a real export moves (the words of the status, a
real column called "Modificata", where the money goes).

    asks      the file holds a word whose meaning changes what is on the books: one question, on it
    reads     nothing in the file changes the bookings' meaning: no question at all
"""

import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from openpyxl import Workbook

HEADERS = [
    "Codice prenotazione",
    "Ospite principale",
    "Email",
    "Telefono",
    "Data prenotazione",
    "Check-in",
    "Check-out",
    "Notti",
    "Tipologia camera",
    "Adulti",
    "Bambini",
    "Canale",
    "Tariffa",
    "Ricavo camere",
    "Valuta",
    "Stato",
    "Note",
]
ROOMS = ("Classic", "Superior", "Deluxe", "Junior Suite")
CHANNELS = ("Booking.com", "Sito diretto", "Expedia", "Telefono / Email", "Walk-in")
RATES = ("Non rimborsabile", "Advance Purchase", "Colazione inclusa", "BAR Flessibile")
NOTES = ("Camera tranquilla", "Parcheggio", "Late check-in", None)
FIRST_STAY = date(2027, 2, 1)
# What the file holds about people: none of it may reach what the page is sent.
PERSONAL_VALUES = ("Ospite Fittizio", "@example.invalid", "+39 000", "Marta Verdi", "Luca Neri")


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    content: bytes
    filename: str
    # What the engine must do: "reads" (no question) or "asks" (exactly these status words).
    outcome: str
    asked_words: tuple[str, ...] = ()
    # A column that means nothing to a booking: nothing may be claimed from it.
    extra_column: str | None = None
    note: str = ""


def _rows(statuses: list[str], *, seed: int, cancelled_revenue: int = 0) -> list[list[object]]:
    rows: list[list[object]] = []
    for index, status in enumerate(statuses):
        step = seed + index
        stay = FIRST_STAY + timedelta(days=step % 27)
        nights = 1 + step % 4
        revenue = (
            0 if status == "Cancellata" and cancelled_revenue == 0 else 120 + (step * 17) % 500
        )
        rows.append(
            [
                f"AX-{seed:02d}{index:03d}",
                f"Ospite Fittizio {step % 11}",
                f"ospite{step % 11}@example.invalid",
                f"+39 000 0000{step:03d}",
                datetime.combine(stay - timedelta(days=10 + step % 40), datetime.min.time()),
                datetime.combine(stay, datetime.min.time()),
                datetime.combine(stay + timedelta(days=nights), datetime.min.time()),
                nights,
                ROOMS[step % len(ROOMS)],
                1 + step % 3,
                step % 2,
                CHANNELS[step % len(CHANNELS)],
                RATES[step % len(RATES)],
                revenue,
                "EUR",
                status,
                NOTES[step % len(NOTES)],
            ]
        )
    return rows


def _book(headers: list[str], rows: list[list[object]], *, title: bool = True) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Prenotazioni"
    if title:
        sheet.append(["REGISTRO PRENOTAZIONI | Hotel di Prova"])
        sheet.append(["Struttura: Hotel di Prova", "Periodo soggiorni: febbraio 2027"])
        sheet.append([])
        sheet.append(["Prenotazioni totali", len(rows)])
        sheet.append([])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    summary = workbook.create_sheet("Riepilogo")
    summary.append(["RIEPILOGO PRENOTAZIONI | Hotel di Prova"])
    summary.append(["Canale", "Prenotazioni"])
    for channel in CHANNELS:
        summary.append([channel, sum(1 for row in rows if channel in row)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _statuses(*counts: tuple[str, int]) -> list[str]:
    """Spread the words through the file, the way a real export has them."""
    words = [word for word, count in counts for _ in range(count)]
    return [words[(index * 7) % len(words)] for index in range(len(words))]


def _with_column(
    name: str, value_of: object, *, after: str = "Stato", seed: int = 3
) -> tuple[list[str], list[list[object]]]:
    """The export with one more column, right after another: `value_of(index)` gives its cells."""
    rows = _rows(_statuses(("Confermata", 50), ("Cancellata", 4)), seed=seed)
    position = HEADERS.index(after) + 1
    headers = [*HEADERS[:position], name, *HEADERS[position:]]
    filled = [
        [*row[:position], value_of(index), *row[position:]]  # type: ignore[operator]
        for index, row in enumerate(rows)
    ]
    return headers, filled


def build_corpus() -> list[Case]:
    cases: list[Case] = []

    def add(
        case_id: str,
        content: bytes,
        outcome: str,
        *words: str,
        extra: str | None = None,
        note: str = "",
    ) -> None:
        cases.append(Case(case_id, content, f"{case_id}.xlsx", outcome, tuple(words), extra, note))

    # --- the word in the status column ------------------------------------------------------------
    for seed, word in enumerate(("Modificata", "Modificato", "Variata", "Da confermare"), start=1):
        add(
            f"word_{word.lower().replace(' ', '_')}",
            _book(
                HEADERS,
                _rows(_statuses(("Confermata", 60), (word, 5), ("Cancellata", 3)), seed=seed),
            ),
            "asks",
            word,
            note="A status word NINFA does not know: it decides what is on the books.",
        )
    add(
        "word_modificata_cancelled_keep_money",
        _book(
            HEADERS,
            _rows(
                _statuses(("Confermata", 60), ("Modificata", 5), ("Cancellata", 3)),
                seed=5,
                cancelled_revenue=1,
            ),
        ),
        "asks",
        "Modificata",
        note="Here the money does not even tell the dead from the alive.",
    )
    add(
        "word_modificata_no_cancelled_at_all",
        _book(HEADERS, _rows(_statuses(("Confermata", 60), ("Modificata", 5)), seed=6)),
        "asks",
        "Modificata",
        note="No way of saying cancelled in this file: the word may be anything.",
    )
    add(
        "two_unknown_words",
        _book(
            HEADERS,
            _rows(
                _statuses(
                    ("Confermata", 50), ("Modificata", 5), ("In attesa", 4), ("Cancellata", 3)
                ),
                seed=7,
            ),
        ),
        "asks",
        "Modificata",
        "In attesa",
    )

    # --- nothing to ask -------------------------------------------------------------------------
    add(
        "only_known_words",
        _book(HEADERS, _rows(_statuses(("Confermata", 60), ("Cancellata", 5)), seed=8)),
        "reads",
    )
    add(
        "english_known_words",
        _book(HEADERS, _rows(_statuses(("Confirmed", 60), ("Cancelled", 5)), seed=9)),
        "reads",
    )

    # --- a real COLUMN about changes: it says nothing about the booking's meaning -----------------
    headers, rows = _with_column("Modificata", lambda i: "Sì" if i % 9 == 0 else "No")
    add(
        "column_modificata_yes_no",
        _book(headers, rows),
        "reads",
        extra="Modificata",
        note="A flag beside the status: nothing canonical needs it.",
    )
    headers, rows = _with_column(
        "Modificata il",
        lambda i: datetime(2027, 1, 3 + i % 20) if i % 7 == 0 else None,
        seed=4,
    )
    add(
        "column_modificata_il_date",
        _book(headers, rows),
        "reads",
        extra="Modificata il",
        note="A date of the exporter's bookkeeping: it must not become the booking date.",
    )
    headers, rows = _with_column("Ultima modifica", lambda i: datetime(2027, 1, 2 + i % 25), seed=5)
    add(
        "column_ultima_modifica_every_row",
        _book(headers, rows),
        "reads",
        extra="Ultima modifica",
        note="Filled on every row, right after the status: still bookkeeping.",
    )
    headers, rows = _with_column(
        "Modificato da", lambda i: ("Marta Verdi", "Luca Neri")[i % 2], seed=6
    )
    add(
        "column_modificato_da_operator",
        _book(headers, rows),
        "reads",
        extra="Modificato da",
        note="Who changed it: a person's name in another form, never mapped.",
    )
    headers, rows = _with_column(
        "Versione", lambda i: 1 + i % 2, after="Codice prenotazione", seed=7
    )
    add(
        "column_version_number",
        _book(headers, rows),
        "reads",
        extra="Versione",
        note="An exporter's counter: not rooms, not nights.",
    )
    return cases
