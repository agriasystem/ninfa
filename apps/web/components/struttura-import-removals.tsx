"use client";

import type { UnderstandingRemovedCost } from "@ninfa/contracts";

import { sourcesCopy } from "@/lib/sources/copy";
import { isoDateText, moneyText } from "@/lib/sources/understanding-format";

const COPY = sourcesCopy.understanding.removals;
const CATEGORIES = sourcesCopy.choices.cost_category as Record<string, string>;

/**
 * The operating costs a complete file would stop counting, one by one (date, supplier, category, amount), before
 * anyone says the file holds everything: the backend lists the first ones and gives how many there are. Nothing is
 * computed here. `question`: while the person is asked; `summary`: the answer is given and the import is next.
 */
export function StrutturaImportRemovals({
  items,
  count,
  mode,
}: {
  items: UnderstandingRemovedCost[];
  count: number;
  mode: "question" | "summary";
}) {
  if (count === 0 || items.length === 0) return null;
  const more = count - items.length;
  return (
    <div className="struttura-preview__attention" role="note">
      <p>{mode === "summary" ? COPY.removed(count) : COPY.absent(count)}</p>
      <ul className="struttura-flow__list">
        {items.map((item, index) => (
          <li key={`${item.date}|${item.supplier}|${index}`}>
            {COPY.item(
              isoDateText(item.date),
              item.supplier,
              item.category === null ? COPY.noCategory : (CATEGORIES[item.category] ?? COPY.noCategory),
              item.amount === null ? COPY.noAmount : moneyText(item.amount, item.currency),
            )}
          </li>
        ))}
      </ul>
      {more > 0 ? <p>{COPY.more(more)}</p> : null}
      <p>{COPY.kept}</p>
    </div>
  );
}
