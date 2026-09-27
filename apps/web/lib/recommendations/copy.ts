/**
 * Static, hand-picked Italian copy for the Recommendation UI (Gate 17), keyed ONLY by the
 * backend's own `action_code`/`risk_notes` (Gate 16) - never by `decision_type`. The Recommendation
 * Engine (`services/api/app/modules/recommendations/`) remains the sole source of truth for WHICH
 * action was chosen; this module only turns a closed code into a human sentence, exactly the way
 * `decisionTypeTitles` (`lib/copy.ts`) turns a `decision_type` into a title - never generated
 * prose, never a second decision about what to show.
 *
 * NINFA proposes a verification, never a business action: every string here uses "rivedi",
 * "verifica", "valuta" or "controlla" - never "riduci", "abbassa", "chiudi", "elimina" or any word
 * that would make a REVIEW action read like an executed one (see ADR 0023, "why copy maps
 * ActionCode, never DecisionType").
 */

export const recommendationCopy = {
  sectionTitle: "Cosa puoi valutare",
  supportingChecksTitle: "Da verificare",
  riskNotesTitle: "Da tenere presente",
  humanReviewNote: "Valuta questa indicazione nel contesto operativo della tua struttura.",
  insufficientContext: "Non ci sono ancora elementi sufficienti per proporti una verifica affidabile.",
} as const;

interface PrimaryActionCopy {
  title: string;
  description: string;
}

/** One entry per primary `ActionCode` Gate 16's `rules.py` can ever produce (one per supported
 * decision_type) - see `recommendation-engine-v1.md`, "Primary actions, one per decision type". */
const PRIMARY_ACTION_COPY = new Map<string, PrimaryActionCopy>([
  [
    "REVIEW_PRICING_AND_AVAILABILITY",
    {
      title: "Rivedi prezzi e disponibilità",
      description:
        "Verifica se prezzi, disponibilità e restrizioni sono coerenti con l'andamento della data.",
    },
  ],
  [
    "REVIEW_DEMAND_POSITIONING",
    {
      title: "Rivedi il posizionamento della data",
      description:
        "Valuta se il posizionamento della data rispetto alla domanda prevista è ancora coerente.",
    },
  ],
  [
    "REVIEW_DISTRIBUTION_MIX",
    {
      title: "Rivedi il mix distributivo",
      description: "Valuta se la distribuzione tra i canali è coerente con l'andamento osservato.",
    },
  ],
  [
    "REVIEW_COST_DRIVERS",
    {
      title: "Verifica cosa sta incidendo sui costi",
      description: "Verifica quali fattori stanno contribuendo allo scostamento di costo rilevato.",
    },
  ],
  [
    "REVIEW_STAFFING_PLAN",
    {
      title: "Rivedi la pianificazione delle ore",
      description: "Verifica se la pianificazione delle ore è coerente con il carico di lavoro previsto.",
    },
  ],
]);

/** One short label per supporting `ActionCode` (`CHECK_*`) `rules.py` can ever produce - a simple
 * item, never a checkbox (there is no persisted "done" state for any of these - see ADR 0023,
 * "why no checkboxes"). */
const SUPPORTING_ACTION_LABEL = new Map<string, string>([
  ["CHECK_CHANNEL_VISIBILITY", "Verifica la visibilità sui canali"],
  ["CHECK_BOOKING_RESTRICTIONS", "Verifica le restrizioni di prenotazione"],
  ["CHECK_PRICING", "Verifica i prezzi"],
  ["CHECK_AVAILABILITY_AND_RESTRICTIONS", "Verifica disponibilità e restrizioni"],
  ["CHECK_DIRECT_CHANNEL_AVAILABILITY", "Verifica la disponibilità sul canale diretto"],
  ["CHECK_DISTRIBUTION_CONFIGURATION", "Verifica la configurazione della distribuzione"],
  ["CHECK_RECENT_COST_ENTRIES", "Verifica le registrazioni di costo recenti"],
  ["CHECK_VOLUME_VS_COST", "Verifica il rapporto tra volumi e costi"],
  ["CHECK_SHIFT_COVERAGE", "Verifica la copertura dei turni"],
  ["CHECK_SCHEDULED_HOURS", "Verifica le ore programmate"],
]);

/** One neutral sentence per closed `RiskNote` - never a numeric/invented risk score, never a
 * red/critical alert (see ADR 0023, "why risk notes are neutral"). */
const RISK_NOTE_COPY = new Map<string, string>([
  ["PRICING_CHANGE_MAY_AFFECT_REVENUE", "Le variazioni di prezzo possono incidere sui ricavi."],
  [
    "STAFFING_CHANGE_MAY_AFFECT_SERVICE",
    "Le variazioni di personale possono incidere sul livello di servizio.",
  ],
  [
    "DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY",
    "Le variazioni distributive possono incidere sulla visibilità.",
  ],
]);

/** `null` for any `action_code` this map does not recognise - fail safe, never a raw enum shown to
 * the user (a future backend action code the frontend has not shipped copy for yet is simply not
 * rendered, never a placeholder). */
export function primaryActionCopyOf(actionCode: string): PrimaryActionCopy | null {
  return PRIMARY_ACTION_COPY.get(actionCode) ?? null;
}

export function supportingActionLabelOf(actionCode: string): string | null {
  return SUPPORTING_ACTION_LABEL.get(actionCode) ?? null;
}

export function riskNoteCopyOf(riskNote: string): string | null {
  return RISK_NOTE_COPY.get(riskNote) ?? null;
}
