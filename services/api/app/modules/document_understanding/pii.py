"""Which columns carry personal data - decided BEFORE anything else looks at the file.

A column of names of employees, names of guests, e-mails, phone numbers, tax codes or IBANs is
recognised from what its header says and from the SHAPE of its values. The answer is a kind, never a
value. A column that may be personal is treated as personal: it is never mapped to a business field,
never sampled for the person to see, and never sent to a provider - not even a pseudonymised sample.

The detection is deliberately cautious on both sides: a header word alone does not make a count of
guests ("Ospiti: 2, 3, 2") a column of names, and values that merely look like two capitalised words
(a department, a channel) do not either.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import fold, stem, stems, tokens


class PiiKind(StrEnum):
    PERSON_NAME = "PERSON_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    TAX_CODE = "TAX_CODE"
    IBAN = "IBAN"


@dataclass(frozen=True, slots=True)
class PiiFinding:
    kind: PiiKind
    by: Literal["HEADER", "VALUES"]
    # The header says so outright (or the values leave no doubt); False = a guess from the shape.
    strong: bool


_PERSON_WORDS = stems(
    "nome cognome name dipendente collaboratore operatore risorsa nominativo ospite guest cliente "
    "customer intestatario staff employee persona referente addetto addetta lavoratore lavoratrice "
    "collega"
)
# Words that make a header NOT a column of names even with a person word in it.
_NOT_A_NAME = stems(
    "numero totale count pax adulti bambini repart tariffa camera struttura hotel fornitore canale "
    "documento fattura prenotazione turno mansione ruolo costo ore"
)
_EMAIL_WORDS = stems("email mail pec")
_PHONE_WORDS = stems("telefono cellulare tel phone mobile cell")
_TAX_WORDS = stems("fiscale cf codfisc")
_IBAN_WORDS = stems("iban")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# A telephone number is written in a few recognisable ways: with the country code ("+39 333
# 1234567"), a landline with its prefix ("06 12345678", "(06) 1234567") or a mobile in groups ("333
# 1234567"). A date ("25/10/2026") or an amount ("1.234.567") is none of them, and a bare run of
# digits is not enough: a reservation number looks just like that.
_PHONE_FORMATS = (
    re.compile(r"^\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,}){1,4}$"),
    re.compile(r"^00\d{1,3}[\s.\-]?\d{2,4}(?:[\s.\-]?\d{3,}){1,3}$"),
    re.compile(r"^\(?0\d{1,3}\)?[\s.\-/]\d{4,8}$"),
    re.compile(r"^3\d{2}[\s.\-/]\d{3}[\s.\-/]?\d{3,4}$"),
    re.compile(r"^3\d{2}[\s.\-/]\d{6,7}$"),
)
_TAX_CODE = re.compile(r"^[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]$")
_IBAN = re.compile(r"^[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}$")
_NAME_WORD = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ'’\-]{1,}$")

# Capitalised words that are not names of people (so two of them in a row are not a name either).
_COMMON_WORDS = stems(
    """
    reception housekeeping piani cucina ristorante sala bar manutenzione spa direzione
    amministrazione booking expedia airbnb diretto direct sito web agenzia telefono camera suite
    doppia singola matrimoniale tripla quadrupla standard superior deluxe confermata cancellata
    annullata arrivato partito hotel residence resort enel energia gas acqua lavanderia
    fornitura servizio servizi colazione colazioni mezza pensione completa
    """
)


# Given names, Italian and the ones a hotel meets everywhere. A column whose values are written
# "Name Surname" or "Surname Name" with one of these in it is a column of people - even when the
# same person appears on many rows (a roster lists each person once a day), which the shape alone
# cannot tell from a column of room types or rate plans ("Front Office", "Best Available").
_GIVEN_NAME_LIST = """
Alessandra Alessandro Alessia Alessio Alice Alberto Andrea Angela Angelo Anna Antonella Antonio
Arianna Barbara Beatrice Benedetta Bruno Camilla Carla Carlo Carmela Caterina Chiara Cinzia
Claudia Claudio Cristian Cristiana Cristina Daniela Daniele Daniel Davide Debora Diego Dario
Domenico Donatella Edoardo Elena Eleonora Elisa Elisabetta Emanuele Emanuela Emilia Emma Enrico
Enzo Erika Eugenio Fabio Fabrizio Federica Federico Filippo Francesca Francesco Franco Gabriele
Gabriella Gaia Gianluca Gianni Giacomo Giada Giorgia Giorgio Giovanna Giovanni Giulia Giuliano
Giulio Giuseppe Giuseppina Gloria Grazia Greta Ilaria Irene Isabella Jacopo Lara Laura Leonardo
Letizia Lorenzo Loredana Luca Lucia Luciano Luigi Luisa Manuela Marco Margherita Maria Mariano
Marina Mario Marta Martina Massimo Matteo Maurizio Michela Michele Mirko Monica Nadia Nicola
Nicoletta Nicolo Noemi Olga Paola Paolo Patrizia Pietro Raffaella Raffaele Renato Riccardo
Roberta Roberto Rosa Rosanna Salvatore Samuele Sandra Sara Serena Sergio Silvia Silvio Simona
Simone Sofia Stefania Stefano Tommaso Teresa Tiziana Tiziano Umberto Valentina Valentino Valeria
Valerio Vanessa Veronica Vincenzo Viola Virginia Vittoria Vittorio Walter Yuri Zoe
Adam Adrian Alex Amanda Ben Charles David Emily Hans Helen James Jean John Julia Karl Kate
Laurent Lisa Mark Michael Nina Oliver Paul Peter Pierre Robert Sarah Sophie Thomas William
"""
_GIVEN_NAMES = frozenset(fold(name) for name in _GIVEN_NAME_LIST.split())


def _header_tokens(header: str) -> frozenset[str]:
    return tokens(header)


def _fraction(texts: tuple[str, ...], pattern: re.Pattern[str]) -> float:
    if not texts:
        return 0.0
    return sum(
        1 for text in texts if pattern.match(text.replace(" ", "") if pattern is _IBAN else text)
    ) / len(texts)


def _phone_numbers(stats: ColumnStats) -> bool:
    """Mostly cells written as telephone numbers."""
    strings = stats.strings
    if len(strings) < 3 or len(strings) < 0.8 * stats.n:
        return False
    phones = sum(1 for text in strings if any(form.match(text) for form in _PHONE_FORMATS))
    return phones / len(strings) >= 0.8


def _name_shaped(text: str) -> bool:
    """Two to four capitalised words, none of them a department, channel or room word."""
    words = text.split()
    if not 2 <= len(words) <= 4 or not all(_NAME_WORD.match(word) for word in words):
        return False
    return not any(stem(fold(word)) in _COMMON_WORDS for word in words)


def _has_given_name(text: str) -> bool:
    """ "Giulia Ferretti" and "Ferretti Giulia": a given name first or last."""
    words = fold(text).split()
    return bool(words) and (words[0] in _GIVEN_NAMES or words[-1] in _GIVEN_NAMES)


def looks_like_person(text: str) -> bool:
    """One value that reads as a person: "Giulia Ferretti", "Ferretti Giulia", or a bare given
    name. (Not a department, a channel, a room: the shape rules out the words a hotel uses.)"""
    return _name_shaped(text) or fold(text) in _GIVEN_NAMES


def looks_like_names(stats: ColumnStats) -> bool:
    """What a column of people's names looks like: values that are two to four capitalised words
    which are not department, channel or room words - and either carry a given name (then the
    same person may well come back on many rows) or are all different from row to row."""
    texts = stats.texts
    if stats.n < 3 or len(texts) < 3 or stats.text_fraction < 0.8:
        return False
    shaped = [text for text in texts if _name_shaped(text)]
    if len(shaped) / len(texts) < 0.8:
        return False
    if sum(1 for text in shaped if _has_given_name(text)) / len(shaped) >= 0.6:
        return True
    return stats.n >= 5 and len(texts) >= 4 and stats.distinct_ratio >= 0.5


def detect_pii(header: str, stats: ColumnStats) -> PiiFinding | None:
    """The personal data a column carries, or None."""
    words = _header_tokens(header)
    texts = stats.texts

    if words & _EMAIL_WORDS or _fraction(texts, _EMAIL) >= 0.6:
        return PiiFinding(PiiKind.EMAIL, "HEADER" if words & _EMAIL_WORDS else "VALUES", True)
    if words & _IBAN_WORDS or _fraction(texts, _IBAN) >= 0.6:
        return PiiFinding(PiiKind.IBAN, "HEADER" if words & _IBAN_WORDS else "VALUES", True)
    if words & _TAX_WORDS or _fraction(texts, _TAX_CODE) >= 0.6:
        return PiiFinding(PiiKind.TAX_CODE, "HEADER" if words & _TAX_WORDS else "VALUES", True)
    if words & _PHONE_WORDS or _phone_numbers(stats):
        return PiiFinding(PiiKind.PHONE, "HEADER" if words & _PHONE_WORDS else "VALUES", True)
    if words & _PERSON_WORDS and not words & _NOT_A_NAME:
        # "Ospiti: 2, 3, 2" is a count, not a guest.
        if stats.n == 0 or stats.text_fraction >= 0.6:
            return PiiFinding(PiiKind.PERSON_NAME, "HEADER", True)
        return None
    if looks_like_names(stats):
        return PiiFinding(PiiKind.PERSON_NAME, "VALUES", False)
    return None


__all__ = ["PiiFinding", "PiiKind", "detect_pii", "looks_like_names", "looks_like_person"]
