import type { RecommendationResponse, RecommendedActionResponse } from "@ninfa/contracts";

import { primaryActionCopyOf, recommendationCopy, riskNoteCopyOf, supportingActionLabelOf } from "./copy";

export interface RecommendationPrimaryViewModel {
  actionCode: string;
  title: string;
  description: string;
}

export interface RecommendationCheckViewModel {
  actionCode: string;
  label: string;
}

export interface RecommendationViewModel {
  /** `false` means "render nothing" - NOT_AVAILABLE, or any status/shape this view-model does not
   * recognise, both fail safe to hidden (see ADR 0023, "why NOT_AVAILABLE is hidden"). */
  visible: boolean;
  title: string;
  primary: RecommendationPrimaryViewModel | null;
  /** At most `MAX_SUPPORTING_CHECKS` (2) - copied from the backend's own order, never reordered,
   * never padded; an unrecognised action_code is dropped, never shown as a raw enum. */
  supporting: RecommendationCheckViewModel[];
  riskNotes: string[];
  /** Shown once for a real AVAILABLE recommendation - never repeated per supporting check, never
   * shown for INSUFFICIENT_CONTEXT (there is nothing yet to ask a human to weigh in on). */
  humanReviewNote: string | null;
  /** Set only for INSUFFICIENT_CONTEXT - a neutral, non-alarming explanation, never a fabricated
   * fallback recommendation. */
  insufficientContextNote: string | null;
}

const HIDDEN: RecommendationViewModel = {
  visible: false,
  title: "",
  primary: null,
  supporting: [],
  riskNotes: [],
  humanReviewNote: null,
  insufficientContextNote: null,
};

function primaryViewModelOf(action: RecommendedActionResponse): RecommendationPrimaryViewModel | null {
  const copy = primaryActionCopyOf(action.action_code);
  if (copy === null) return null;
  return { actionCode: action.action_code, title: copy.title, description: copy.description };
}

function supportingViewModelsOf(actions: RecommendedActionResponse[]): RecommendationCheckViewModel[] {
  const checks: RecommendationCheckViewModel[] = [];
  for (const action of actions) {
    const label = supportingActionLabelOf(action.action_code);
    if (label !== null) {
      checks.push({ actionCode: action.action_code, label });
    }
  }
  return checks;
}

function riskNotesOf(action: RecommendedActionResponse): string[] {
  const notes: string[] = [];
  for (const code of action.risk_notes) {
    const note = riskNoteCopyOf(code);
    if (note !== null) notes.push(note);
  }
  return notes;
}

/**
 * Pure, testable: the backend's own `RecommendationResponse` (Gate 16) -> what Decision Detail
 * (Gate 17) shows. Never derives copy from `decision_type` - only from `action_code`/`risk_notes`,
 * exactly as the backend decided them (see ADR 0023, "why DecisionType does not choose the
 * action"). Never recomputes `status`, `confidence` or which action was chosen - it only maps a
 * closed vocabulary to Italian and decides visibility.
 *
 * `AVAILABLE` with a `primary_action` this map cannot resolve (or `null`, which the backend never
 * sends for AVAILABLE, but a future contract drift could) fails safe to hidden, the same as
 * `NOT_AVAILABLE` - never a half-rendered section with no actual review action in it.
 */
export function recommendationViewModel(recommendation: RecommendationResponse): RecommendationViewModel {
  if (recommendation.status === "INSUFFICIENT_CONTEXT") {
    return {
      ...HIDDEN,
      visible: true,
      title: recommendationCopy.sectionTitle,
      insufficientContextNote: recommendationCopy.insufficientContext,
    };
  }

  if (recommendation.status !== "AVAILABLE" || recommendation.primary_action === null) {
    return HIDDEN;
  }

  const primary = primaryViewModelOf(recommendation.primary_action);
  if (primary === null) return HIDDEN;

  return {
    visible: true,
    title: recommendationCopy.sectionTitle,
    primary,
    supporting: supportingViewModelsOf(recommendation.supporting_checks),
    riskNotes: riskNotesOf(recommendation.primary_action),
    humanReviewNote: recommendationCopy.humanReviewNote,
    insufficientContextNote: null,
  };
}
