"""Personal data stays personal however it is typed.

A header or a value can be disguised by accident (a zero-width space copied in from a web page, a
no-break space from Word) or on purpose (letters borrowed from the Cyrillic alphabet, the words of
"Codice Fiscale" glued together). None of that may make NINFA lose track of what is personal:
the header must still classify the column, the value must still be masked in the text that goes to
the browser, and neither may reach a language model. Tests here come in three layers - the header
classifier, the text masks, and the whole path (a real file, the real service, a model that
records what it is shown).

No database, no network, no model: real bytes through the real understanding service.
"""

import json
from collections.abc import Callable

import pytest

from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.sanitize import REMOVED, clean_text
from app.modules.data_sources.understanding import UnderstandAnswers, UnderstandingService
from app.modules.document_understanding.pii import PiiKind, detect_pii
from app.modules.document_understanding.pii_text import header_word_sets, normalize, projection
from app.modules.document_understanding.redaction import MARK, PersonalDataGuard
from app.modules.document_understanding.stats import column_stats
from app.modules.ingestion.models import DataSourceDomain
from tests.hardening_support import by_header, payload_of, xlsx
from tests.import_ai_support import Recorder

ZWSP, ZWNJ, ZWJ, BOM, NBSP, NNBSP, SHY = (
    "​",
    "‌",
    "‍",
    "﻿",
    " ",
    " ",
    "­",
)

# --- the header classifier ---

FAMILIES: list[tuple[str, PiiKind]] = [
    ("Nome Dipendente", PiiKind.PERSON_NAME),
    ("Cognome Dipendente", PiiKind.PERSON_NAME),
    ("Nome Ospite", PiiKind.PERSON_NAME),
    ("Cognome Ospite", PiiKind.PERSON_NAME),
    ("Guest Name", PiiKind.PERSON_NAME),
    ("First Name", PiiKind.PERSON_NAME),
    ("Last Name", PiiKind.PERSON_NAME),
    ("Surname", PiiKind.PERSON_NAME),
    ("Employee Name", PiiKind.PERSON_NAME),
    ("Email", PiiKind.EMAIL),
    ("E-mail", PiiKind.EMAIL),
    ("Telefono", PiiKind.PHONE),
    ("Cellulare", PiiKind.PHONE),
    ("Phone", PiiKind.PHONE),
    ("Codice Fiscale", PiiKind.TAX_CODE),
    ("Tax Code", PiiKind.TAX_CODE),
    ("Fiscal Code", PiiKind.TAX_CODE),
    ("IBAN", PiiKind.IBAN),
]

# What the cells of such a column would look like if the values themselves gave nothing away: the
# header is the only evidence, as it is for a column of surnames.
NEUTRAL = ["Rossi", "Bianchi", "Verdi", "Neri", "Gallo", "Serra"]


def _disguises(phrase: str) -> dict[str, str]:
    """Every way of typing the same header that a person still reads as the same words."""
    words = phrase.split()
    first = words[0]
    inside = first[:2] + "{c}" + first[2:]
    glued = "".join(words)
    disguises: dict[str, str] = {
        "plain": phrase,
        "upper": phrase.upper(),
        "lower": phrase.lower(),
        "mixed case": "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(phrase)),
        "glued": glued,
        "glued lower": glued.lower(),
        "glued upper": glued.upper(),
        "accents": phrase.replace("o", "ó").replace("e", "é", 1),
        "cyrillic look-alikes": phrase.replace("o", "о").replace("a", "а").replace("e", "е"),
        "full-width": "".join(chr(ord(c) + 0xFEE0) if "!" < c < "\x7f" else c for c in phrase),
    }
    for name, char in (
        ("zero-width space", ZWSP),
        ("zero-width non-joiner", ZWNJ),
        ("zero-width joiner", ZWJ),
        ("BOM", BOM),
        ("soft hyphen", SHY),
    ):
        disguises[f"{name} inside a word"] = phrase.replace(first, inside.format(c=char), 1)
        disguises[f"{name} first"] = char + phrase
        if len(words) > 1:
            disguises[f"{name} between words"] = char.join(words)
            disguises[f"{name} replacing the space"] = glued.replace(first, first + char, 1)
    for name, char in (("no-break space", NBSP), ("narrow no-break space", NNBSP)):
        disguises[name] = char.join(words) if len(words) > 1 else phrase + char
    return disguises


CASES = [
    pytest.param(header, kind, label, disguised, id=f"{header}|{label}")
    for header, kind in FAMILIES
    for label, disguised in _disguises(header).items()
]


@pytest.mark.parametrize(("header", "kind", "label", "disguised"), CASES)
def test_a_disguised_header_classifies_the_column_exactly_as_the_plain_one(
    header: str, kind: PiiKind, label: str, disguised: str
) -> None:
    plain = detect_pii(header, column_stats(NEUTRAL))
    hidden = detect_pii(disguised, column_stats(NEUTRAL))

    assert plain is not None and plain.kind == kind, f"the plain header {header!r} must classify"
    assert hidden is not None, f"{label}: {disguised!r} lost the personal-data header"
    assert hidden.kind == kind and hidden.by == "HEADER"


def test_the_two_readings_of_a_zero_width_character_are_both_tried() -> None:
    # it was inside a word ("Co<ZWSP>dice") or it stood where a space should be
    # ("Codice<ZWSP>Fiscale")
    def says(header: str, *words: str) -> bool:
        return any(set(words) <= reading for reading in header_word_sets(header))

    assert says(f"Co{ZWSP}dice{ZWSP}Fiscale", "codic", "fiscal")
    assert says(f"Nome{ZWSP}Ospite", "nome", "ospit")
    assert says(f"Cogno{ZWSP}me", "cognom")
    # ...and the wrong reading never leaks its invented words into the right one
    assert not any({"nome", "numer"} <= reading for reading in header_word_sets(f"No{ZWSP}me"))


@pytest.mark.parametrize(
    "header",
    [
        "Hotel",
        "Camere",
        "Canale",
        "Telefonico",
        "Nomenclatura",
        "Data arrivo",
        "Stato prenotazione",
    ],
)
def test_ordinary_headers_are_not_taken_for_personal_data(header: str) -> None:
    assert detect_pii(header, column_stats(NEUTRAL)) is None


def test_tax_alone_is_a_vat_column_not_a_tax_code() -> None:
    assert detect_pii("Tax", column_stats(["22", "22", "10"])) is None
    assert detect_pii("Tax amount", column_stats(["22.5", "10.1", "5.2"])) is None


def test_a_hidden_hourly_rate_is_still_locked() -> None:
    from app.modules.data_sources.semantics_labor import hourly_or_known_exclusion

    for header in (
        "Costo orario",
        f"Costo{ZWSP}orario",
        f"Paga{SHY}oraria",
        f"Tariffa{NBSP}oraria",
        f"EUR/{ZWSP}h",
        "Cоsto оrario",
    ):
        assert hourly_or_known_exclusion(header) == "HOURLY_RATE", header


# --- the text masks ---

PERSONAL_VALUES = {
    "email": "mario.rossi@example.com",
    "iban": "IT60X0542811101000000123456",
    "tax code": "RSSMRA85T10A562S",
    "phone": "+39 333 1234567",
}


def _hide(value: str, how: str) -> str:
    middle = len(value) // 2
    chars = {
        "zero-width space": ZWSP,
        "zero-width non-joiner": ZWNJ,
        "zero-width joiner": ZWJ,
        "BOM": BOM,
        "soft hyphen": SHY,
    }
    if how in chars:
        return value[:middle] + chars[how] + value[middle:]
    if how == "cyrillic":
        return value.replace("o", "о").replace("a", "а").replace("e", "е").replace("S", "Ѕ")
    if how == "full-width @":
        return value.replace("@", "＠")
    if how == "control character":
        return value[:middle] + "\x00" + value[middle:]
    raise AssertionError(how)


HIDINGS = [
    "zero-width space",
    "zero-width non-joiner",
    "zero-width joiner",
    "BOM",
    "soft hyphen",
    "cyrillic",
    "full-width @",
    "control character",
]


@pytest.mark.parametrize("how", HIDINGS)
@pytest.mark.parametrize("kind", list(PERSONAL_VALUES))
def test_a_personal_value_with_a_disguise_is_removed_before_it_goes_to_a_model(
    kind: str, how: str
) -> None:
    value = PERSONAL_VALUES[kind]
    if kind != "email" and how == "full-width @":
        pytest.skip("no @ to widen")

    cleaned = clean_text(f"nota: {_hide(value, how)} fine")

    assert REMOVED in cleaned, f"{kind} hidden with {how} survived: {cleaned!r}"
    plain = normalize(cleaned)
    for fragment in (value[:6], value[-6:]):
        assert fragment not in plain


@pytest.mark.parametrize("how", HIDINGS)
@pytest.mark.parametrize("kind", list(PERSONAL_VALUES))
def test_a_personal_value_with_a_disguise_is_masked_in_the_text_shown_to_a_person(
    kind: str, how: str
) -> None:
    value = PERSONAL_VALUES[kind]
    if kind != "email" and how == "full-width @":
        pytest.skip("no @ to widen")
    text = f"Contatto: {_hide(value, how)}, grazie"

    masked = PersonalDataGuard().clean(text)

    assert MARK in masked, f"{kind} hidden with {how} was not found"
    assert masked.startswith("Contatto: ") and masked.endswith(", grazie")  # only the value goes
    assert value[:6] not in normalize(masked) and value[-6:] not in normalize(masked)


@pytest.mark.parametrize("how", ["zero-width space", "BOM", "soft hyphen", "cyrillic"])
def test_a_name_of_the_file_is_masked_whatever_way_it_is_written_elsewhere(how: str) -> None:
    guard = PersonalDataGuard.for_columns([(PiiKind.PERSON_NAME, ["Giulia Ferretti"])])
    written = _hide("Giulia Ferretti", how)

    assert guard.clean(f"Responsabile: {written}") == f"Responsabile: {MARK}"
    # ...and the other way round: the file holds the disguised cell, the text has the plain name
    disguised = PersonalDataGuard.for_columns([(PiiKind.PERSON_NAME, [written])])
    assert disguised.clean("Responsabile: Giulia Ferretti") == f"Responsabile: {MARK}"


def test_projection_maps_every_character_back_to_the_original() -> None:
    text = f"a{ZWSP}b c"

    normalized, starts, ends = projection(text)

    assert normalized == "ab c"
    assert (starts[0], ends[0]) == (0, 1) and (starts[1], ends[1]) == (2, 3)


def test_a_whole_cyrillic_word_is_left_alone() -> None:
    assert normalize("Дата прихода") == "Дата прихода"
    assert normalize("Cоdice") == "Codice"  # mixed with Latin: that is a disguise


# --- the whole path: a real file, the real service, a model that records what it sees ---


def _service(provider: Recorder | None) -> UnderstandingService:
    from uuid import UUID

    from app.core.tenant import TenantContext
    from app.modules.data_sources.smart_import import SmartImportService

    tenant = TenantContext(UUID(int=1))
    resolver = ImportUnderstandingResolver(provider)
    return UnderstandingService(None, tenant, SmartImportService(None, tenant), resolver)  # type: ignore[arg-type]


SURNAMES = ["Ferretti", "Rinaldi", "Orlandi", "Dallari", "Carrara", "Olivieri", "Bassi", "Monti"]
CODES = ["RSSMRA85T10A562S", "VRDLGU90A01H501Z", "BNCLRA70C41F205X", "NREGNN80M15D612W"] * 2
MAILS = [f"ospite{i}@example.org" for i in range(8)]
PHONES = [f"+39 333 12345{i:02d}" for i in range(8)]
IBANS = [f"IT60X05428111010000001234{i:02d}" for i in range(8)]


def _bookings_with_hidden_personal_columns(
    hide: Callable[[str], str],
) -> tuple[bytes, dict[str, list[str]]]:
    """A bookings file whose guest columns have disguised headers and values that, on their own,
    give nothing away to a header reader (surnames alone)."""
    from datetime import datetime, timedelta

    header: list[object] = [
        "Codice prenotazione",
        "Arrivo",
        "Partenza",
        hide("Cognome Ospite"),
        hide("Codice Fiscale"),
        hide("Email"),
        hide("Telefono"),
        hide("IBAN"),
        "Colonna 9",
    ]
    rows: list[list[object]] = [header]
    for i in range(8):
        arrival = datetime(2026, 11, 14) + timedelta(days=i)
        rows.append(
            [
                f"RES-{i}",
                arrival,
                arrival + timedelta(days=2),
                SURNAMES[i],
                CODES[i],
                MAILS[i],
                PHONES[i],
                IBANS[i],
                f"x{i}",
            ]
        )
    values = {"surname": SURNAMES, "tax": CODES, "mail": MAILS, "phone": PHONES, "iban": IBANS}
    return xlsx(rows), values


@pytest.mark.parametrize(
    "hide",
    [
        lambda h: h,
        lambda h: h.replace(" ", ZWSP),
        lambda h: h.replace(" ", "") if " " in h else h[:2] + ZWNJ + h[2:],
        lambda h: BOM + h[:3] + SHY + h[3:],
        lambda h: h.replace("o", "о").replace("e", "е"),
    ],
    ids=["plain", "zero-width-as-space", "glued", "bom+soft-hyphen", "cyrillic"],
)
def test_no_personal_value_reaches_the_browser_or_the_model_under_a_disguised_header(
    hide: Callable[[str], str],
) -> None:
    content, values = _bookings_with_hidden_personal_columns(hide)
    model = Recorder()

    inspection = _service(model).understand(
        DataSourceDomain.BOOKINGS, "ospiti.xlsx", content, UnderstandAnswers(), False, None, False
    )

    browser = normalize(payload_of(inspection))
    sent = normalize(" ".join(model.payloads))
    for kind, cells in values.items():
        for cell in cells:
            assert cell not in browser, f"{kind} value {cell!r} reached the browser"
            assert cell not in sent, f"{kind} value {cell!r} reached the model"
    assert model.requests, "the file has an unreadable column: the model is expected to be asked"
    document = json.loads(model.payloads[0])
    classes = {c["pii"] for c in document["columns"] if c["pii"]}
    assert {"PII_PERSON_NAME", "PII_TAX_CODE", "PII_EMAIL", "PII_PHONE", "PII_IBAN"} <= classes
    # the personal columns are not fields of the booking either
    placed = {h: c.field for h, c in by_header(inspection).items() if c.field}
    assert not any(f in {"guest_name", "email"} for f in placed.values())
