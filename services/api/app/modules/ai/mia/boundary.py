"""The boundary of the OPEN property: a person who asks Mia for the data of ANOTHER structure gets
the same plain answer, from the application, before any model or tool is involved.

Mia answers about the property the conversation belongs to, under the asking user's own access
(ADR 0055). A question that names or points at another structure ("l'altra struttura", "Hotel
Miramare") cannot be answered from here - whether that structure is one the person manages, one of
another account, or one that does not exist. The answer must be:

* CLEAR about what it is: an access boundary of NINFA, not a limit of Mia or of a model - and that
  nothing about the other structure was read;
* THE SAME in every case. It is written before any lookup, so it cannot tell a property the person
  may open from one they may not, or from a name nobody has: it never checks whether the structure
  exists, never repeats the name the person typed, and reads nothing (the same "404-equivalent"
  rule the API applies to a foreign conversation or decision id).

The detection is deliberately narrow and lexical (an explicit "altra struttura", or a hotel-like
noun followed by a capitalised name that is not part of this property's own name), AND it requires
that the person asks for data. Anything it misses reaches the model, whose policy states the same
boundary (rule 18); anything it catches is a question that could not have been answered anyway.
"""

import re

OTHER_PROPERTY_ANSWER = (
    "Da questa conversazione non posso consultare i dati di un'altra struttura: è un confine di "
    "accesso di NINFA, non un limite di Mia, e non ho letto alcun dato che la riguardi. Apri "
    "quella struttura in NINFA e chiedimelo da lì. Su quella che hai aperto ora posso invece "
    "rispondere subito."
)

_NOUNS = r"(?:struttur[ae]|propriet[àa]|hotel|alberg(?:o|hi)|sed[ei]|resort|residence|b&b)"
# "l'altra struttura", "un altro hotel", "le altre strutture": an explicit pointer at another one.
_ANOTHER = re.compile(r"(?<!\w)altr[aeio]\s+" + _NOUNS + r"(?!\w)")
# "Hotel Quirino Zzyx Beach", "Albergo Fuoriporta": a hotel-like noun and a NAME (capitalised).
_NAMED = re.compile(
    r"(?<!\w)(?i:hotel|albergo|residence|resort|b&b|agriturismo|villa|casa vacanze)"
    r"((?:\s+[A-ZÀ-Ý][\w'’-]*)+)"
)
# The person is asking for data, not asking how the product handles several structures.
_CUE_STEMS = (
    "occupa",
    "pien",
    "prenotaz",
    "ricav",
    "camere",
    "personale",
    "decision",
    "importaz",
    "situazione",
    "performance",
    "risultat",
    "andamento",
)
_CUE_WORDS = (
    "adr",
    "cpor",
    "pickup",
    "costo",
    "costi",
    "dati",
    "numeri",
    "canali",
    "ota",
    "import",
    "come va",
    "come vanno",
    "com'è",
)
_HOW_TO = re.compile(
    r"(?<!\w)(?:come|dove)\s+(?:posso\s+|faccio\s+a\s+|si\s+)?"
    r"(?:aggiung|colleg|cre[ao]|configur|import|gestisc|attiv)"
)
_WORDS = re.compile(r"[\w]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {word.lower() for word in _WORDS.findall(text)}


def _names_another_structure(question: str, own_name: str) -> bool:
    if _ANOTHER.search(question.lower()):
        return True
    own = _tokens(own_name)
    for match in _NAMED.finditer(question):
        named = _tokens(match.group(1))
        if named and not named <= own:
            return True
    return False


def _asks_for_data(lowered: str) -> bool:
    if _HOW_TO.search(lowered):
        return False
    if any(re.search(r"(?<!\w)" + re.escape(stem), lowered) for stem in _CUE_STEMS):
        return True
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lowered) for word in _CUE_WORDS)


def asks_for_another_property(question: str, own_name: str) -> bool:
    """True when `question` asks for DATA of a structure other than the open one (`own_name`)."""
    return _asks_for_data(question.lower()) and _names_another_structure(question, own_name)


__all__ = ["OTHER_PROPERTY_ANSWER", "asks_for_another_property"]
