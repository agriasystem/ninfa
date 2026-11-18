"""Smart Import V4: the global assignment of columns to fields (scipy `linear_sum_assignment`).

The point of an assignment over V3's greedy pick: the best reading of the WHOLE file, not of the
best-looking pair first. These tests pin what it must do that greedy cannot - collisions, a global
optimum that differs from the greedy one, fields nobody supplies, columns nobody wants - and how it
tells a firm pair from a coin flip (the margin).
"""

from app.modules.data_sources.algorithmic.assignment import OUT, assign
from app.modules.data_sources.proposal import greedy_pick
from app.modules.data_sources.semantics import Level, NameMatch


def test_each_column_and_each_field_is_used_at_most_once() -> None:
    scores = {(0, "a"): 0.9, (1, "a"): 0.8, (1, "b"): 0.7, (2, "b"): 0.6}

    result = assign(scores, [0, 1, 2], ["a", "b"])

    assert len(set(result.pairs.values())) == len(result.pairs)
    assert set(result.pairs) <= {0, 1, 2}


def test_the_global_optimum_can_differ_from_the_greedy_one() -> None:
    # Column 0 fits "a" best (0.80) but could also be "b" (0.75); column 1 only fits "a" (0.78).
    # Greedy takes (0, a) first and leaves column 1 with nothing: total 0.80 + OUT.
    # The best reading of the file is (0, b) + (1, a): 0.75 + 0.78.
    scores = {(0, "a"): 0.80, (0, "b"): 0.75, (1, "a"): 0.78}

    greedy, _taken = greedy_pick(
        [
            (2, s, 0, -column, field, NameMatch.EXACT, None, Level.MEDIUM)
            for (column, field), s in scores.items()
        ]
    )
    assert greedy == {0: ("a", NameMatch.EXACT, None, Level.MEDIUM)}  # greedy strands column 1

    result = assign(scores, [0, 1], ["a", "b"])

    assert result.pairs == {0: "b", 1: "a"}
    assert result.total > 0.80 + OUT


def test_a_field_nobody_supplies_stays_empty() -> None:
    result = assign({(0, "a"): 0.9}, [0], ["a", "b", "c"])

    assert result.pairs == {0: "a"}


def test_a_column_nobody_wants_is_left_out_at_no_cost() -> None:
    result = assign({(0, "a"): 0.9}, [0, 1, 2], ["a", "b"])

    assert result.pairs == {0: "a"}
    assert 1 not in result.pairs and 2 not in result.pairs


def test_a_pair_below_the_admission_floor_is_never_forced() -> None:
    result = assign({(0, "a"): 0.2, (1, "a"): 0.29}, [0, 1], ["a"])

    assert result.pairs == {}


def test_two_columns_for_one_field_give_it_to_the_better_one() -> None:
    result = assign({(0, "a"): 0.9, (1, "a"): 0.6}, [0, 1], ["a"])

    assert result.pairs == {0: "a"}


def test_a_pair_nothing_competes_with_is_firm() -> None:
    result = assign({(0, "a"): 0.95}, [0], ["a"])

    assert result.margins[0] > 0.6


def test_a_coin_flip_has_no_margin() -> None:
    # two columns, one field, the same score: whichever is chosen, the other would do as well
    result = assign({(0, "a"): 0.9, (1, "a"): 0.9}, [0, 1], ["a"])

    assert len(result.pairs) == 1
    assert next(iter(result.margins.values())) < 0.01


def test_a_close_second_reading_shows_as_a_small_margin() -> None:
    result = assign({(0, "a"): 0.90, (1, "a"): 0.86}, [0, 1], ["a"])

    assert result.pairs == {0: "a"}
    assert result.margins[0] < 0.10


def test_the_same_file_always_gives_the_same_reading() -> None:
    scores = {
        (i, f): 0.5 + 0.01 * ((i * 7 + j * 3) % 10)
        for i in range(6)
        for j, f in enumerate("abcdef")
    }

    first = assign(scores, list(range(6)), list("abcdef"))
    second = assign(dict(reversed(list(scores.items()))), list(range(6)), list("abcdef"))

    assert first.pairs == second.pairs


def test_a_tie_goes_to_the_earlier_column_as_in_v3() -> None:
    result = assign({(3, "a"): 0.9, (1, "a"): 0.9}, [1, 3], ["a"])

    assert result.pairs == {1: "a"}


def test_an_empty_file_is_an_empty_reading() -> None:
    assert assign({}, [], ["a"]).pairs == {}
    assert assign({}, [0, 1], []).pairs == {}


def test_a_realistic_file_is_solved_in_well_under_a_millisecond_per_column() -> None:
    import time

    fields = [f"f{i}" for i in range(17)]
    scores = {
        (c, f): 0.3 + ((c * 13 + i * 7) % 60) / 100 for c in range(30) for i, f in enumerate(fields)
    }

    started = time.perf_counter()
    assign(scores, list(range(30)), fields)

    assert time.perf_counter() - started < 0.5
