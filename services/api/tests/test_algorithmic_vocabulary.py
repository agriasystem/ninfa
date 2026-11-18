"""Smart Import V4: the hospitality vocabulary is consistent, independent of the held-out
words, and not tied to one PMS.

The vocabulary is data. What can go wrong with data is a typo in a key, two fields claiming one
phrase, a phrase listed as both a field and its opposite, and - the one that would make the
benchmark meaningless - a phrase copied from the held-out list the challenge corpus is built from.
"""

import re
from collections import defaultdict

import pytest

from app.modules.data_sources.algorithmic import vocabulary
from app.modules.data_sources.algorithmic.header import normalize
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR
from app.modules.ingestion.models import DataSourceDomain
from tests.benchmarks.smart_import_v3.openai_intelligence import HELD_OUT

SEMANTICS = {
    DataSourceDomain.BOOKINGS: BOOKINGS,
    DataSourceDomain.LABOR: LABOR,
    DataSourceDomain.COSTS: COSTS,
}


def _key(phrase: str) -> tuple[str, ...]:
    return tuple(sorted(normalize(phrase).words))


def test_the_version_is_stamped() -> None:
    assert re.fullmatch(r"hospitality-\d{4}\.\d{2}\.\d+", vocabulary.VERSION)


@pytest.mark.parametrize("domain", list(SEMANTICS))
def test_every_key_is_a_real_field_of_that_kind_of_data(domain: DataSourceDomain) -> None:
    fields = set(SEMANTICS[domain].fields)

    assert set(vocabulary.ALIASES[domain]) <= fields
    assert set(vocabulary.NOT_THE_FIELD.get(domain, {})) <= fields


@pytest.mark.parametrize("domain", list(SEMANTICS))
def test_no_phrase_belongs_to_two_fields_of_one_kind_of_data(domain: DataSourceDomain) -> None:
    owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for field, phrases in vocabulary.ALIASES[domain].items():
        for phrase in phrases:
            owners[_key(phrase)].add(field)

    shared = {key: fields for key, fields in owners.items() if len(fields) > 1}

    assert not shared, f"phrases claimed by two fields: {shared}"


@pytest.mark.parametrize("domain", list(SEMANTICS))
def test_a_phrase_is_never_both_a_field_and_not_that_field(domain: DataSourceDomain) -> None:
    for field, phrases in vocabulary.NOT_THE_FIELD.get(domain, {}).items():
        mine = {_key(p) for p in vocabulary.ALIASES[domain].get(field, ())}
        assert not mine & {_key(p) for p in phrases}, field


@pytest.mark.parametrize("domain", list(SEMANTICS))
def test_the_vocabulary_does_not_contradict_what_the_importers_already_name(
    domain: DataSourceDomain,
) -> None:
    """A phrase the importer's own names give to one field is never given to another here."""
    sem = SEMANTICS[domain]
    known: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for field, spec in sem.fields.items():
        for name in spec.exact:
            known[_key(name)].add(field)
    conflicts = []
    for field, phrases in vocabulary.ALIASES[domain].items():
        for phrase in phrases:
            owners = known.get(_key(phrase), set())
            if owners and field not in owners:
                conflicts.append((phrase, field, sorted(owners)))

    assert not conflicts, conflicts


def test_no_phrase_of_the_held_out_list_was_copied_into_the_vocabulary() -> None:
    """The challenge corpus replaces headers with words the rules do not know. A vocabulary that
    contains them would be graded on its own homework."""
    held_out = {_key(word) for words in HELD_OUT.values() for word in words}
    used = {
        _key(phrase)
        for phrases_by_field in (*vocabulary.ALIASES.values(), *vocabulary.NOT_THE_FIELD.values())
        for phrases in phrases_by_field.values()
        for phrase in phrases
    }

    assert not held_out & used, sorted(held_out & used)


def test_no_phrase_names_a_pms_or_a_vendor() -> None:
    brands = (
        "opera",
        "protel",
        "mews",
        "cloudbeds",
        "fidelio",
        "mirus",
        "passepartout",
        "zucchetti",
    )
    text = " ".join(
        phrase.lower()
        for phrases_by_field in vocabulary.ALIASES.values()
        for phrases in phrases_by_field.values()
        for phrase in phrases
    )

    assert not any(re.search(rf"\b{brand}\b", text) for brand in brands)


def test_the_vocabulary_is_large_enough_to_matter_and_covers_italian_and_english() -> None:
    total = sum(len(p) for fields in vocabulary.ALIASES.values() for p in fields.values())
    italian = sum(
        1
        for fields in vocabulary.ALIASES.values()
        for phrases in fields.values()
        for phrase in phrases
        if re.search(r"\b(data|numero|importo|totale|ore|fattura|camere|prenotazione)\b", phrase)
    )

    assert total >= 600
    assert italian >= 100
