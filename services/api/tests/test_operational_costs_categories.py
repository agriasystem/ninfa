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
"""

from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.intelligence.costs.repository import CostLineRepository
from tests.invoice_support import CostWorld
from tests.operational_costs_support import (
    all_records,
    confirm_operational,
    cost_row,
    current_records,
    delta,
    full,
    import_costs,
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
