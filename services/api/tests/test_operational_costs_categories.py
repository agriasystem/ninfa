"""Operating costs with no document number: the category is metadata, never identity (ADR 0057).

A reclassification ("Lavanderia" -> "Pulizie") is the SAME cost, so the category stays out of what a
cost is. But two economically identical rows stated with two categories are TWO costs and each keeps
its own: the distinction comes from the multiplicity of the economic fingerprint, and the category
is the classification attached to each occurrence. Occurrences are matched, never assigned by
position: the order of the rows of a CSV is never used.

  A  two categories at once: two costs, one category each
  B  the same two rows reordered: nothing happens, no category swaps
  C  one row, one recategorization: the same cost, the new category, one current observation
  D  two duplicates, one recategorized: still two costs, one classification changes
  E  a duplicate is added                 F  a duplicate is removed by a complete file
  G  the same change as PARTIAL           H  the same change as DELTA

and, named after the final correctness gate, T1-T4, T9, T11, T12, T21 and T22.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.costs.repository import CostLineRepository
from tests.invoice_support import CostWorld
from tests.operational_costs_support import (
    OPERATIONAL_COLUMNS,
    OPERATIONAL_HEADERS,
    all_records,
    confirm_operational,
    cost_row,
    current_records,
    delta,
    full,
    import_costs,
    operational_csv,
    partial,
    removals,
    stated,
)
from tests.support import BookingFactory

LAUNDRY = "LAUNDRY"
CLEANING = "CLEANING"
MAINTENANCE = "MAINTENANCE"


def row(category: str) -> list[Any]:
    """The same cost, economically (date, supplier, description, amounts), in a category."""
    return cost_row(category=category, description="Servizio camere ottobre", net="80.00")


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    costs = CostWorld.create(db_session, factory)
    confirm_operational(costs)
    return costs


def categories(session: Session, world: CostWorld) -> list[str]:
    return sorted(stated(session, world).values())


def observed(session: Session, world: CostWorld) -> list[tuple[str, int]]:
    """What the cost analysis reads of October: (category, number of lines)."""
    aggregates = CostLineRepository(session, world.context).monthly_aggregates(
        world.tenant.property.id, date(2026, 10, 1), date(2026, 10, 31)
    )
    return sorted((a.cost_category.value, a.line_count) for a in aggregates)


# --- A. two categories at once --------------------------------------------------------------


def test_two_identical_rows_in_two_categories_are_two_costs_one_category_each(
    db_session: Session, world: CostWorld
) -> None:
    result = import_costs(world, [row(LAUNDRY), row(CLEANING)])

    assert result.succeeded and result.invoices_created == 2
    assert categories(db_session, world) == [CLEANING, LAUNDRY]
    keys = list(stated(db_session, world))
    assert len({key.rsplit("#", 1)[0] for key in keys}) == 1  # one economic cost, counted twice
    assert observed(db_session, world) == [(CLEANING, 1), (LAUNDRY, 1)]


def test_the_assignment_of_categories_to_occurrences_does_not_depend_on_the_file_order(
    db_session: Session, factory: BookingFactory
) -> None:
    one = CostWorld.create(db_session, factory)
    other = CostWorld.create(db_session, factory)
    confirm_operational(one)
    confirm_operational(other)

    import_costs(one, [row(LAUNDRY), row(CLEANING)])
    import_costs(other, [row(CLEANING), row(LAUNDRY)])

    def by_number(costs: CostWorld) -> list[tuple[str, str]]:
        return sorted(
            (key.rsplit("#", 1)[1], category) for key, category in stated(db_session, costs).items()
        )

    assert by_number(one) == by_number(other)


# --- B. reordered -------------------------------------------------------------------------------


def test_the_same_two_rows_reordered_change_nothing(db_session: Session, world: CostWorld) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING)])
    before = stated(db_session, world)

    again = import_costs(world, [row(CLEANING), row(LAUNDRY)])

    assert again.invoices_created == 0 and again.invoices_revised == 0
    assert again.invoices_unchanged == 2 and not again.changed_data
    assert stated(db_session, world) == before  # no category moved to another occurrence
    assert len(all_records(db_session, world)) == 2


# --- C. one recategorization --------------------------------------------------------------------


def test_a_recategorization_is_the_same_cost_with_the_new_category(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY)])
    [before] = current_records(db_session, world)

    result = import_costs(world, [row(CLEANING)])

    assert result.succeeded and result.invoices_created == 0 and result.invoices_revised == 1
    assert result.records_removed == 0 and result.changed_data
    [after] = current_records(db_session, world)
    assert after.source_record_key == before.source_record_key  # the same cost
    assert after.revision == 2 and after.id != before.id
    assert after.source_import_job_id != before.source_import_job_id  # the provenance of each
    assert categories(db_session, world) == [CLEANING]
    assert len(all_records(db_session, world)) == 2 and removals(db_session, world) == []
    # the analysis sees ONE observation, in the new category, never both
    assert observed(db_session, world) == [(CLEANING, 1)]


def test_a_file_that_states_no_category_says_nothing_and_changes_nothing(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY)])

    again = import_costs(world, [row("")])  # the cell is empty: the source states no category

    assert again.invoices_revised == 0 and again.invoices_unchanged == 1
    assert categories(db_session, world) == [LAUNDRY]


def test_importing_a_file_again_never_reclassifies_anything(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING)])

    again = import_costs(world, [row(LAUNDRY), row(CLEANING)])

    assert not again.changed_data and again.invoices_revised == 0
    assert len(all_records(db_session, world)) == 2


# --- D. two duplicates, one recategorized -------------------------------------------------------


def test_with_two_duplicates_only_the_recategorized_one_changes(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING)])
    kept = next(
        r
        for r in current_records(db_session, world)
        if stated(db_session, world)[r.source_record_key] == LAUNDRY
    )

    result = import_costs(world, [row(LAUNDRY), row(MAINTENANCE)])

    assert result.invoices_created == 0 and result.invoices_revised == 1
    assert len(current_records(db_session, world)) == 2  # never a third cost
    assert categories(db_session, world) == [LAUNDRY, MAINTENANCE]
    survivor = next(r for r in current_records(db_session, world) if r.id == kept.id)
    assert survivor.revision == 1  # the one that did not change was not touched
    assert observed(db_session, world) == [(LAUNDRY, 1), (MAINTENANCE, 1)]


# --- E. a duplicate is added --------------------------------------------------------------------


def test_adding_one_more_duplicate_creates_exactly_one_new_cost(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING)])

    grown = import_costs(world, [row(LAUNDRY), row(CLEANING), row(CLEANING)])

    assert grown.invoices_created == 1 and grown.invoices_unchanged == 2
    assert categories(db_session, world) == [CLEANING, CLEANING, LAUNDRY]


# --- F, G, H. a duplicate is no longer in the file ------------------------------------------------


def test_a_complete_file_without_one_duplicate_takes_away_exactly_one(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING), row(CLEANING)])

    result = import_costs(world, [row(LAUNDRY), row(CLEANING)], scope=full(1))

    assert result.records_removed == 1 and result.invoices_created == 0
    assert categories(db_session, world) == [CLEANING, LAUNDRY]
    assert len(removals(db_session, world)) == 1


@pytest.mark.parametrize(("name", "scope"), [("PARTIAL", partial()), ("DELTA", delta())])
def test_the_same_change_as_a_part_or_as_news_takes_nothing_away(
    db_session: Session, world: CostWorld, name: str, scope: Any
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING), row(CLEANING)])

    result = import_costs(world, [row(LAUNDRY), row(CLEANING)], scope=scope)

    assert result.records_removed == 0, name
    assert categories(db_session, world) == [CLEANING, CLEANING, LAUNDRY]
    assert removals(db_session, world) == []


def test_what_a_complete_file_would_take_away_is_counted_the_way_it_is_applied(
    db_session: Session, world: CostWorld
) -> None:
    """A recategorization is not an absence: the figure shown is the figure applied."""
    import_costs(world, [row(LAUNDRY), row(CLEANING)])

    # the file holds both costs, one in another category: nothing is missing from it
    result = import_costs(world, [row(LAUNDRY), row(MAINTENANCE)], scope=full(0))

    assert result.succeeded and result.records_removed == 0 and result.invoices_revised == 1
    assert categories(db_session, world) == [LAUNDRY, MAINTENANCE]


def test_a_removed_duplicate_comes_back_with_the_category_the_file_states(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY), row(CLEANING), row(CLEANING)])
    import_costs(world, [row(LAUNDRY), row(CLEANING)], scope=full(1))

    back = import_costs(world, [row(LAUNDRY), row(CLEANING), row(MAINTENANCE)])

    assert back.records_restored == 1 and back.invoices_created == 0
    assert categories(db_session, world) == [CLEANING, LAUNDRY, MAINTENANCE]


# --- Final correctness gate: T1-T12, T21, T22 named after the gate ---------------------------
# Already proved above (mapping in the gate report): T5/T6 (the PARTIAL/DELTA test here and
# `test_a_part_of_the_period_or_only_the_news_takes_nothing_away` in test_operational_costs.py),
# T8 (`test_two_identical_rows_in_two_categories_are_two_costs_one_category_each`) and T10
# (`test_the_same_two_rows_reordered_change_nothing`). What follows is what was missing.

X = row(LAUNDRY)


def total(session: Session, world: CostWorld) -> Decimal:
    """What the cost analysis counts for October, all categories together."""
    aggregates = CostLineRepository(session, world.context).monthly_aggregates(
        world.tenant.property.id, date(2026, 10, 1), date(2026, 10, 31)
    )
    return sum((a.net_cost for a in aggregates), Decimal(0))


def keys(session: Session, world: CostWorld) -> list[str]:
    return sorted(r.source_record_key for r in current_records(session, world))


def test_t1_three_identical_rows_imported_again_are_a_no_op(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])
    before = keys(db_session, world)

    again = import_costs(world, [X, X, X])

    assert again.succeeded and not again.changed_data
    assert again.invoices_created == 0 and again.invoices_revised == 0
    assert again.invoices_unchanged == 3 and again.records_removed == 0
    assert keys(db_session, world) == before and len(all_records(db_session, world)) == 3


def test_t2_three_identical_rows_reordered_among_others_are_a_no_op(
    db_session: Session, world: CostWorld
) -> None:
    other = cost_row(day="2026-10-06", description="Acqua ottobre", net="40.00")
    import_costs(world, [X, other, X, X])
    before = stated(db_session, world)

    again = import_costs(world, [X, X, other, X])

    assert not again.changed_data and again.invoices_unchanged == 4
    assert stated(db_session, world) == before


def test_t3_a_complete_file_with_four_identical_rows_adds_exactly_one(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])

    grown = import_costs(world, [X, X, X, X], scope=full(0))

    assert grown.succeeded and grown.invoices_created == 1 and grown.records_removed == 0
    assert grown.invoices_unchanged == 3
    assert [k.rsplit("#", 1)[1] for k in keys(db_session, world)] == ["1", "2", "3", "4"]
    assert total(db_session, world) == Decimal("320.00")


def test_t4_a_complete_file_with_two_identical_rows_takes_one_away_and_the_total_follows(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [X, X, X])
    assert total(db_session, world) == Decimal("240.00")

    result = import_costs(world, [X, X], scope=full(1))

    assert result.records_removed == 1 and result.invoices_created == 0
    assert len(current_records(db_session, world)) == 2
    [removal] = removals(db_session, world)  # the tombstone of the one that no longer counts
    assert removal.invoice_id not in {r.id for r in current_records(db_session, world)}
    assert len(all_records(db_session, world)) == 3  # the record itself stays, as history
    assert total(db_session, world) == Decimal("160.00")


def test_t9_the_same_file_in_reverse_order_gives_the_same_state_on_a_clean_source(
    db_session: Session, factory: BookingFactory
) -> None:
    """T9 (as reformulated): the same number of costs, the same categories, the same totals."""
    one = CostWorld.create(db_session, factory)
    other = CostWorld.create(db_session, factory)
    confirm_operational(one)
    confirm_operational(other)

    import_costs(one, [row(LAUNDRY), row(CLEANING)])
    import_costs(other, [row(CLEANING), row(LAUNDRY)])

    assert len(current_records(db_session, one)) == len(current_records(db_session, other)) == 2
    assert categories(db_session, one) == categories(db_session, other) == [CLEANING, LAUNDRY]
    assert observed(db_session, one) == observed(db_session, other)
    assert total(db_session, one) == total(db_session, other) == Decimal("160.00")


@pytest.mark.parametrize(
    ("name", "scope"),
    [("T11 FULL", full(0)), ("T12 PARTIAL", partial()), ("T12 DELTA", delta())],
)
def test_t11_t12_a_reclassification_is_the_same_cost_whatever_the_file_says_it_holds(
    db_session: Session, world: CostWorld, name: str, scope: Any
) -> None:
    """X#1 Lavanderia, then the same row in Pulizie: one cost, the new category, the same total, one
    current observation in the analysis, and the change kept in the history (revision 2 beside 1).
    The row being in the file speaks for that row, whatever the file says it holds."""
    import_costs(world, [row(LAUNDRY)])
    [before] = current_records(db_session, world)

    result = import_costs(world, [row(CLEANING)], scope=scope)

    assert result.succeeded, name
    assert result.invoices_created == 0 and result.invoices_revised == 1, name
    assert result.records_removed == 0 and removals(db_session, world) == [], name
    [after] = current_records(db_session, world)
    assert after.source_record_key == before.source_record_key, name
    assert categories(db_session, world) == [CLEANING], name
    assert total(db_session, world) == Decimal("80.00"), name
    assert observed(db_session, world) == [(CLEANING, 1)], name
    history = sorted((r.revision, r.source_record_key) for r in all_records(db_session, world))
    assert history == [(1, before.source_record_key), (2, before.source_record_key)], name


def test_t11_the_same_reclassification_imported_again_is_a_no_op(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY)])
    import_costs(world, [row(CLEANING)], scope=full(0))

    again = import_costs(world, [row(CLEANING)], scope=full(0))

    assert not again.changed_data and again.invoices_revised == 0
    assert len(all_records(db_session, world)) == 2


# --- T21: the matching never crosses a source, a period or a kind of identity -----------------


def test_t21_the_same_cost_in_another_source_is_never_matched_nor_reclassified(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    other = CostWorld(
        db_session, world.tenant, factory.data_source(world.tenant.property, DataSourceDomain.COSTS)
    )
    confirm_operational(other)
    import_costs(world, [row(LAUNDRY)])

    elsewhere = import_costs(other, [row(CLEANING)], scope=full(0))

    assert elsewhere.invoices_created == 1 and elsewhere.invoices_revised == 0
    assert elsewhere.records_removed == 0
    assert categories(db_session, world) == [CLEANING, LAUNDRY]  # both stand, neither changed


def test_t21_the_same_cost_on_another_day_is_never_matched_nor_reclassified(
    db_session: Session, world: CostWorld
) -> None:
    import_costs(world, [row(LAUNDRY)])
    next_day = cost_row(
        day="2026-10-06",
        category=CLEANING,
        description="Servizio camere ottobre",
        net="80.00",
    )

    result = import_costs(world, [next_day], scope=partial())

    assert result.invoices_created == 1 and result.invoices_revised == 0
    assert categories(db_session, world) == [CLEANING, LAUNDRY]


def test_t21_a_numbered_invoice_with_the_same_content_is_never_matched(
    db_session: Session, world: CostWorld
) -> None:
    """A real document of the same source with the same content is another kind of identity:
    an operating cost never pairs with it, never reclassifies it, and a complete file never
    takes it."""
    numbered_headers = ["Numero", *OPERATIONAL_HEADERS]
    world.confirm(
        headers=numbered_headers,
        columns={**OPERATIONAL_COLUMNS, "invoice_number": {"column": "Numero"}},
    )
    assert (
        world.service()
        .import_file(
            world.source.id,
            filename="fatture.csv",
            content=operational_csv([["FT/1", *row(LAUNDRY)]], numbered_headers),
        )
        .succeeded
    )
    confirm_operational(world)

    result = import_costs(world, [row(CLEANING)], scope=full(0))

    assert result.invoices_created == 1 and result.invoices_revised == 0
    assert result.records_removed == 0
    assert categories(db_session, world) == [CLEANING, LAUNDRY]
    origins = sorted(r.identity_origin.value for r in current_records(db_session, world))
    assert origins == ["DOCUMENT_NUMBER", "SYNTHETIC_COST_RECORD"]


# --- T22: an occurrence a complete file took away, back again ---------------------------------


def test_t22_an_occurrence_taken_away_and_back_is_restored_with_a_coherent_history(
    db_session: Session, world: CostWorld
) -> None:
    """The existing tombstone semantics (ADR 0057 decision 7): the removal row stays forever,
    the record itself stays, and the occurrence comes back as the NEXT REVISION of the same key -
    never a new key, never a duplicate."""
    import_costs(world, [row(LAUNDRY), row(LAUNDRY), row(LAUNDRY)])
    taken = import_costs(world, [row(LAUNDRY), row(LAUNDRY)], scope=full(1))
    assert taken.records_removed == 1
    [removal] = removals(db_session, world)
    gone = next(r for r in all_records(db_session, world) if r.id == removal.invoice_id)

    back = import_costs(world, [row(LAUNDRY), row(LAUNDRY), row(LAUNDRY)])

    assert back.records_restored == 1 and back.invoices_created == 0
    current = current_records(db_session, world)
    assert len(current) == 3 and len({r.source_record_key for r in current}) == 3  # no duplicate
    restored = next(r for r in current if r.source_record_key == gone.source_record_key)
    assert restored.revision == gone.revision + 1 and restored.id != gone.id
    assert removals(db_session, world) == [removal]  # the tombstone is history, never deleted
    assert total(db_session, world) == Decimal("240.00")
    # the same file again: nothing more comes back, nothing is duplicated
    again = import_costs(world, [row(LAUNDRY), row(LAUNDRY), row(LAUNDRY)])
    assert not again.changed_data and len(all_records(db_session, world)) == 4
