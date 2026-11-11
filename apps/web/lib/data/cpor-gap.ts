import type { DataCostOccupancy } from "@ninfa/contracts";

import { datiCopy } from "@/lib/data/copy";
import { formatBusinessDateItalian } from "@/lib/date/property-date";

/** What is missing under a month's cost per occupied room, said exactly: one line for each thing a missing
 * day lacks. `inventoryHelps` says whether configuring the inventory closes some of it. */
export interface CostOccupancyGap {
  lines: string[];
  inventoryHelps: boolean;
}

/**
 * The cause of a cost per occupied room that cannot be calculated, from the counts the backend sends
 * (`DataCostOccupancy`): the days without an inventory, the days the bookings do not cover, the days whose
 * rooms are uncertain and the days that wait for the next analysis. `null` when nothing is missing (or the
 * backend sent no basis) - the caller then falls back to its generic words, never the other way round.
 * Nothing is counted here: every number is the backend's.
 */
export function costOccupancyGap(basis: DataCostOccupancy | null, month: string): CostOccupancyGap | null {
  if (basis === null) return null;
  const copy = datiCopy.costs.cporGap;
  const lines: string[] = [];
  if (basis.days_without_inventory > 0 && basis.first_day_without_inventory !== null) {
    lines.push(
      copy.withoutInventory(
        basis.days_without_inventory,
        month,
        formatBusinessDateItalian(basis.first_day_without_inventory),
      ),
    );
  }
  if (basis.days_outside_bookings > 0) lines.push(copy.outsideBookings(basis.days_outside_bookings, month));
  if (basis.uncertain_days > 0) lines.push(copy.uncertain(basis.uncertain_days, month));
  if (basis.days_awaiting_rebuild > 0) lines.push(copy.awaiting(basis.days_awaiting_rebuild, month));
  return lines.length === 0 ? null : { lines, inventoryHelps: basis.days_without_inventory > 0 };
}
