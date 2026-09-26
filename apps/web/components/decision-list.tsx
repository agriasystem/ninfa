import type { FeedItemResponse } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import { buildDecisionCardData } from "@/lib/decisions/card-view-models";
import { decisionDetailRoute } from "@/lib/routes";

import { DecisionCard } from "./decision-card";

const MAX_VISIBLE_DECISIONS = 5;

export interface DecisionListProps {
  /** Already ordered `priority_rank ASC` by the backend - never re-sorted here. */
  items: FeedItemResponse[];
  /** The property these decisions belong to - needed only to build each card's Decision Detail
   * link (Gate 15); the feed request itself already used it. */
  propertyId: string;
}

/** Presents AT MOST 5 decisions - the API still returns every triggered candidate; this only
 * ever slices the array for display (`items.slice(0, 5)`), never filters or reorders it. */
export function DecisionList({ items, propertyId }: DecisionListProps) {
  const visible = items.slice(0, MAX_VISIBLE_DECISIONS);
  const remaining = items.length - visible.length;

  return (
    <section className="decision-list">
      <h2 className="decision-list__heading">{copy.today.actionRequiredHeading}</h2>
      <ol className="decision-list__items">
        {visible.map((item) => (
          <li key={item.decision_id}>
            <DecisionCard
              data={buildDecisionCardData(item)}
              href={decisionDetailRoute(propertyId, item.decision_id)}
            />
          </li>
        ))}
      </ol>
      {remaining > 0 ? (
        <p className="decision-list__more">{copy.today.moreDecisions(remaining)}</p>
      ) : null}
    </section>
  );
}
