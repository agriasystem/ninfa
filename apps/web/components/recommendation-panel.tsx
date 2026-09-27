import type { RecommendationResponse } from "@ninfa/contracts";

import { recommendationCopy } from "@/lib/recommendations/copy";
import { recommendationViewModel } from "@/lib/recommendations/view-model";

export interface RecommendationPanelProps {
  recommendation: RecommendationResponse;
}

/**
 * "Cosa puoi valutare" (Gate 17): a single, additive Decision Detail section, always rendered
 * AFTER Evidenze and BEFORE Evoluzione (see ADR 0023, "why evidence comes first"). Renders nothing
 * at all when the recommendation is not visible (NOT_AVAILABLE, or a status/action this frontend
 * does not recognise - `recommendationViewModel` already decided that).
 *
 * Read-only by construction: no button, no checkbox, no `onClick` anywhere in this component - it
 * takes no callback prop, so there is nothing here that COULD execute, approve or apply anything.
 */
export function RecommendationPanel({ recommendation }: RecommendationPanelProps) {
  const vm = recommendationViewModel(recommendation);
  if (!vm.visible) return null;

  return (
    <section className="recommendation-panel">
      <h2 className="recommendation-panel__heading">{vm.title}</h2>

      {vm.insufficientContextNote !== null ? (
        <p className="recommendation-panel__insufficient">{vm.insufficientContextNote}</p>
      ) : (
        <>
          {vm.primary !== null ? (
            <div className="recommendation-panel__primary">
              <p className="recommendation-panel__primary-title">{vm.primary.title}</p>
              <p className="recommendation-panel__primary-description">{vm.primary.description}</p>
            </div>
          ) : null}

          {vm.supporting.length > 0 ? (
            <div className="recommendation-panel__supporting">
              <h3>{recommendationCopy.supportingChecksTitle}</h3>
              <ul>
                {vm.supporting.map((check) => (
                  <li key={check.actionCode}>{check.label}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {vm.riskNotes.length > 0 ? (
            <div className="recommendation-panel__risk-notes">
              <h3>{recommendationCopy.riskNotesTitle}</h3>
              <ul>
                {vm.riskNotes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {vm.humanReviewNote !== null ? (
            <p className="recommendation-panel__human-review">{vm.humanReviewNote}</p>
          ) : null}
        </>
      )}
    </section>
  );
}
