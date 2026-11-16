"""Universal Understanding 2 - free text about a person, and addresses, are personal data.

A guest's request ("Richiede culla in camera", "Allergia ai latticini"), an employee's remark, a
home address: none of it is something NINFA reads, and none of it may be shown as an example value
of an unmapped column. Every rule here has its counter-example: a column called "Note" over short
codes is not a story about anybody, and "Nota di credito" is a kind of invoice.

No database, no network, no model.
"""

import pytest

from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.stats import ColumnStats, column_stats

SENTENCES = (
    "Richiede culla in camera",
    "Allergia ai latticini, colazione senza lattosio",
    "Arrivo previsto dopo le 22:00",
    "Anniversario, preparare una bottiglia in camera",
)
ADDRESSES = ("Via Roma 12, Torino", "Piazza Garibaldi 3, Milano", "Corso Italia 40, Bari")


def stats_of(values: tuple[str, ...]) -> ColumnStats:
    return column_stats(list(values * 3))


@pytest.mark.parametrize(
    "header",
    [
        "Special Requests",
        "Richieste speciali",
        "Note",
        "Notes",
        "Annotazioni",
        "Preferenze",
        "Allergie",
        "Remarks",
    ],
)
def test_free_text_about_somebody_is_a_personal_note(header: str) -> None:
    finding = detect_pii(header, stats_of(SENTENCES))
    assert finding is not None and finding.kind == PiiKind.NOTE


@pytest.mark.parametrize("header", ["Guest notes", "Commenti ospite", "Note cliente"])
def test_a_note_about_a_named_party_stays_personal(header: str) -> None:
    # (already personal through the party word: the note word must never make it LESS so)
    assert detect_pii(header, stats_of(SENTENCES)) is not None


@pytest.mark.parametrize("header", ["Indirizzo", "Indirizzo di residenza", "Address", "Domicilio"])
def test_an_address_column_is_personal(header: str) -> None:
    finding = detect_pii(header, stats_of(ADDRESSES))
    assert finding is not None and finding.kind == PiiKind.ADDRESS


# --- counter-examples: what must NOT be taken for a personal note / address ---


def test_a_note_column_of_numbers_is_not_free_text() -> None:
    assert detect_pii("Note", column_stats([1, 2, 3, 4, 5, 6])) is None


@pytest.mark.parametrize("header", ["Nota di credito", "Credit note", "Note di accredito"])
def test_a_credit_note_is_a_document_not_a_remark(header: str) -> None:
    assert detect_pii(header, stats_of(SENTENCES)) is None


@pytest.mark.parametrize("header", ["Reparto", "Descrizione", "Stato", "Canale", "Tariffa"])
def test_other_text_columns_are_not_notes(header: str) -> None:
    assert detect_pii(header, stats_of(("Sala", "Bar", "Cucina", "Reception"))) is None


# --- found by the real pilot shadow validation: "Street" was sent to the model as an example --


@pytest.mark.parametrize("header", ["Street", "Street address", "Strada", "Viale", "Piazza"])
def test_the_words_of_a_street_make_a_column_an_address(header: str) -> None:
    finding = detect_pii(header, stats_of(("Via Inventata 12",)))
    assert finding is not None and finding.kind == PiiKind.ADDRESS


def test_a_street_of_a_customer_is_personal_whichever_word_decides() -> None:
    assert detect_pii("Customer street", stats_of(("Via Inventata 12",))) is not None


@pytest.mark.parametrize("header", ["Sede", "Luogo", "Dove", "Colonna 9", "X"])
@pytest.mark.parametrize(
    "values",
    [
        ADDRESSES,
        ("Via Inventata 12",),
        ("12 High Street", "221 Baker Street", "5 Station Road"),
    ],
)
def test_values_written_as_street_addresses_are_personal_under_any_header(
    header: str, values: tuple[str, ...]
) -> None:
    finding = detect_pii(header, stats_of(values))
    assert finding is not None and finding.kind == PiiKind.ADDRESS and finding.by == "VALUES"


@pytest.mark.parametrize(
    ("header", "values"),
    [
        # "via" is the way a booking came, not a street
        ("Prenotato via", ("Booking.com", "Expedia", "Diretto")),
        ("Canale", ("Booking.com", "Via Booking", "Diretto")),
        ("Reparto", ("Sala", "Bar", "Cucina", "Reception")),
        ("Tipologia camera", ("Doppia", "Singola", "Suite Vista Mare")),
        ("Tariffa", ("Best Available", "Non Rimborsabile", "Early Booking")),
    ],
)
def test_a_text_column_that_is_not_an_address_stays_what_it_was(
    header: str, values: tuple[str, ...]
) -> None:
    assert detect_pii(header, stats_of(values)) is None
