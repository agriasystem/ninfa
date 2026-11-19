"""Smart Import V4: what values prove, what they rule out, and what columns say about each other.

A status, a channel, a department, a currency, a booking code: their values can name them with no
helpful header. A column of dates is not a room count, channel names are not a status, a column with
cents is not a booking code: those are VETOES, and they matter as much as the proofs because a wrong
confident reading costs more than a question. A number is never proof of an amount, a count or
hours.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.bookings.parsers import Cell
from app.modules.data_sources.algorithmic.profile import ColumnProfile, Primitive, profile_column
from app.modules.data_sources.algorithmic.relational import relations_of
from app.modules.data_sources.algorithmic.values import Sem, proof_of, read_values, veto
from app.modules.data_sources.column_profile import ColumnSample
from app.modules.document_understanding.stats import column_stats
from app.modules.ingestion.models import DataSourceDomain
from tests.algorithmic_support import (
    CHANNELS,
    DEPARTMENTS,
    MONEY,
    ROOMS,
    STATUSES,
    codes,
    sample,
    stay,
    table,
)

B, C = DataSourceDomain.BOOKINGS, DataSourceDomain.COSTS


def profile(header: str, values: Sequence[Cell]) -> ColumnProfile:
    s = sample(0, header, values)
    return profile_column(s, column_stats(s.values))


# --- the profile
# ------------------------------------------------------------------------------------


def test_a_profile_counts_and_shapes_nothing_more() -> None:
    p = profile("Importo", [12.5, 99.0, None, 130.25, 80.0, 45.0])

    assert p.rows == 6
    assert p.non_null == 5
    assert p.null_rate == pytest.approx(1 / 6)
    assert p.primitive == Primitive.DECIMAL
    assert p.minimum is not None and p.maximum is not None
    assert (p.minimum, p.maximum) == (Decimal("12.5"), Decimal("130.25"))
    assert p.negative == 0 and p.positive == 5
    assert set(p.describe()) >= {"primitive", "uniqueness", "numeric", "date", "status"}


def test_a_profile_is_deterministic() -> None:
    first = profile("Stato", STATUSES)
    second = profile("Stato", STATUSES)

    assert first == second


def test_a_column_of_words_keeps_its_commonest_values_and_a_personal_one_keeps_none() -> None:
    words = profile("Stato", STATUSES)
    s = sample(0, "Ospite", ["Mario Rossi", "Anna Verdi", "Luca Neri", "Mario Rossi"] * 3)
    personal = profile_column(s, column_stats(s.values), locked=True)

    assert dict(words.top_values)["Confirmed"] == 6
    assert personal.top_values == ()
    assert personal.personal


def test_top_values_are_short_and_never_free_text() -> None:
    long_notes = [f"Il cliente ha chiesto una camera tranquilla numero {i}" for i in range(12)]

    assert profile("Note", long_notes).top_values == ()


def test_the_profile_reads_how_numbers_are_written() -> None:
    cents = profile("A", ["12,50", "99,00", "130,25", "80,00", "45,10"])
    percent = profile("B", ["22%", "10%", "22%", "4%", "22%"])
    money = profile("C", ["€ 1.200,00", "€ 950,50", "€ 80,00", "€ 2.300,00", "€ 45,00"])

    assert cents.cents_share == 1.0
    assert percent.percent_like == 1.0
    assert money.money_like >= 0.6


# --- positive proof
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "sem"),
    [
        (STATUSES, Sem.STATUS),
        (DEPARTMENTS, Sem.DEPARTMENT),
        (["EUR"] * 8, Sem.CURRENCY),
        (["Alimentari", "Bevande", "Pulizie", "Utenze", "Manutenzione"] * 2, Sem.CATEGORY),
    ],
)
def test_a_vocabulary_column_names_itself(values: list[str], sem: Sem) -> None:
    assert proof_of(profile("x", values), sem) >= 0.9


def test_a_booking_code_names_itself_by_being_different_on_every_row_in_one_shape() -> None:
    assert proof_of(profile("x", codes()), Sem.IDENTIFIER) >= 0.9


@pytest.mark.parametrize(
    ("values", "sem"),
    [
        (MONEY, Sem.MONEY),
        (ROOMS, Sem.COUNT),
        ([8, 6, 8, 7, 6, 8, 8, 6], Sem.HOURS),
        ([22, 22, 10, 4, 22, 22], Sem.PERCENT),
    ],
)
def test_a_number_alone_is_never_proof_of_an_amount_a_count_hours_or_a_rate(
    values: list[Any], sem: Sem
) -> None:
    assert proof_of(profile("x", values), sem) == 0.0


def test_a_repeating_code_or_a_short_column_proves_nothing() -> None:
    assert proof_of(profile("x", ["A1", "A1", "A2", "A2"] * 3), Sem.IDENTIFIER) == 0.0
    assert proof_of(profile("x", ["Confirmed", "Cancelled"]), Sem.STATUS) == 0.0  # 2 values


def test_a_status_column_that_is_mostly_unknown_words_proves_nothing() -> None:
    assert proof_of(profile("x", ["Alfa", "Beta", "Gamma", "Alfa", "Beta"] * 2), Sem.STATUS) == 0.0


def test_personal_data_is_never_a_proof() -> None:
    s = sample(0, "x", DEPARTMENTS)
    p = profile_column(s, column_stats(s.values), locked=True)

    assert proof_of(p, Sem.DEPARTMENT) == 0.0


# --- negative evidence ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "sem", "why"),
    [
        (CHANNELS, Sem.STATUS, "channel names"),
        (STATUSES, Sem.CHANNEL, "booking statuses"),
        (DEPARTMENTS, Sem.STATUS, "departments"),
        ([date(2026, 10, d) for d in range(1, 13)], Sem.COUNT, "dates"),
        ([date(2026, 10, d) for d in range(1, 13)], Sem.MONEY, "dates"),
        (["Alfa", "Beta", "Gamma", "Delta", "Eps", "Zeta"] * 2, Sem.MONEY, "words"),
        (["12,50", "99,00", "130,25", "80,00", "45,10", "70,00"], Sem.IDENTIFIER, "amounts"),
        (["22%", "10%", "22%", "4%", "22%", "22%"], Sem.COUNT, "percentages"),
        ([-8, -6, 8, 7, -6, 8], Sem.HOURS, "negative"),
        (list(range(100, 112)), Sem.STATUS, "numbers"),
    ],
)
def test_the_values_rule_out_what_they_cannot_be(values: list[Any], sem: Sem, why: str) -> None:
    reason = veto(profile("x", values), sem)

    assert reason is not None and why in reason


def test_a_status_over_channel_names_is_ruled_out_in_a_real_reading() -> None:
    evidence = read_values(B, "status", 0.8, profile("Stato", CHANNELS))

    assert evidence.veto is not None
    assert "channel" in evidence.veto


def test_a_sparse_or_short_column_is_not_ruled_out_on_thin_evidence() -> None:
    assert veto(profile("x", [None, None, None]), Sem.STATUS) is None
    assert veto(profile("x", [12.5]), Sem.IDENTIFIER) is None


def test_a_list_of_amounts_may_be_all_different_without_being_a_code() -> None:
    whole = profile("Importo", [1200, 950, 80, 2300, 45, 310, 780, 1210, 665, 99])

    assert veto(whole, Sem.MONEY) is None  # all different, all whole: still money, not a code


# --- relations between columns
# ----------------------------------------------------------------------


def _bookings_table(order: tuple[int, int, int]) -> list[ColumnSample]:
    booked, arrival, departure = stay()
    columns = [booked, arrival, departure]
    named = {f"Col {i}": columns[order[i]] for i in range(3)}
    return table(named)


def test_three_dates_in_order_are_booked_arrival_departure_with_no_helpful_header() -> None:
    samples = _bookings_table((0, 1, 2))
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    relational = relations_of(B, samples, profiles)

    assert relational.proof[(0, "booked_at")] > 0.8
    assert relational.proof[(1, "check_in")] > 0.8
    assert relational.proof[(2, "check_out")] > 0.8


def test_the_order_of_the_columns_in_the_file_does_not_matter() -> None:
    samples = _bookings_table((2, 0, 1))  # departure, booked, arrival
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    relational = relations_of(B, samples, profiles)

    assert relational.proof[(0, "check_out")] > 0.8
    assert relational.proof[(1, "booked_at")] > 0.8
    assert relational.proof[(2, "check_in")] > 0.8


def test_two_dates_that_fit_two_orderings_are_not_named() -> None:
    same = [date(2026, 10, d) for d in range(1, 13)]
    samples = table({"A": same, "B": list(same), "C": list(same)})
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    assert not relations_of(B, samples, profiles).proof


def test_a_stay_of_two_dates_gives_a_bonus_but_no_proof_of_the_booking_date() -> None:
    _booked, arrival, departure = stay()
    samples = table({"A": arrival, "B": departure})
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    relational = relations_of(B, samples, profiles)

    assert relational.bonus[(0, "check_in")] > 0
    assert relational.bonus[(1, "check_out")] > 0
    assert not relational.proof


def test_net_plus_vat_equals_total_names_the_three_amounts_of_a_register() -> None:
    net = [100.0, 250.0, 80.0, 1000.0, 45.0, 310.0]
    vat = [round(n * 0.22, 2) for n in net]
    gross = [round(a + b, 2) for a, b in zip(net, vat, strict=True)]
    samples = table({"A": gross, "B": net, "C": vat})
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    relational = relations_of(C, samples, profiles)

    assert relational.bonus[(1, "invoice_net_amount")] > 0
    assert relational.bonus[(2, "invoice_tax_amount")] > 0
    assert relational.bonus[(0, "invoice_gross_amount")] > 0


def test_amounts_that_do_not_add_up_are_no_evidence() -> None:
    samples = table(
        {"A": [100.0, 250.0, 80.0, 1000.0, 45.0], "B": [5.0, 7.0, 9.0, 3.0, 8.0], "C": [1.0] * 5}
    )
    profiles = [profile_column(s, column_stats(s.values)) for s in samples]

    assert not relations_of(C, samples, profiles).bonus


# --- the profile cache ----------------------------------------------------------------------------


def test_a_profile_is_computed_once_per_sample_and_nothing_outlives_it() -> None:
    import gc

    from app.modules.data_sources.algorithmic import profile as module

    column = sample(0, "x", [1, 2, 3, 4, 5, 6])
    before = len(module._cache)

    first = profile_column(column, column_stats(column.values))
    second = profile_column(column, column_stats(column.values))

    assert first is second
    assert len(module._cache) == before + 1
    del column
    gc.collect()
    assert (
        len(module._cache) == before
    )  # the entry went with the sample: no file outlives its request
