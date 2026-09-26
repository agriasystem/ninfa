import type { DecisionStatus, DecisionType, LifecycleTransition, SourceStatus } from "@ninfa/contracts";

/**
 * Centralised Italian copy for Oggi UI V1 (Gate 14). No i18n framework: a single object, one
 * source per string, so wording changes never require hunting through components (see
 * docs/architecture/oggi-ui-v1.md, "Copy - Italian default").
 */
export const copy = {
  brand: {
    wordmark: "NINFA",
  },
  login: {
    heading: "Accedi a NINFA",
    emailLabel: "Email",
    passwordLabel: "Password",
    submit: "Accedi",
    submitting: "Accesso in corso…",
    // The backend's own error is deliberately generic (INVALID_CREDENTIALS covers unknown email,
    // wrong password AND a locked account alike) - the frontend must stay just as generic.
    invalidCredentials: "Email o password non corretti.",
    genericError: "Non siamo riusciti ad accedere. Riprova.",
  },
  shell: {
    logout: "Esci",
  },
  property: {
    selectorLabel: "Struttura",
    emptyStateTitle: "Nessuna struttura disponibile",
    emptyStateBody: "Il tuo account non è associato a nessuna struttura.",
  },
  today: {
    heading: "Oggi",
    refresh: "Aggiorna",
    refreshing: "Aggiornamento…",
    loadErrorGeneric: "Non siamo riusciti a caricare l'analisi. Riprova.",
    retry: "Riprova",
    notProcessedTitle: "Analisi non ancora disponibile",
    notProcessedBody: "NINFA non ha ancora completato l'analisi per oggi.",
    dataQualityTitle: "Analisi parziale",
    dataQualityBody:
      "Alcuni controlli non dispongono ancora di dati sufficienti. NINFA non mostra conclusioni incerte.",
    dataQualityInsufficientCount: (count: number) => `${count} in attesa di dati sufficienti`,
    dataQualitySuppressedCount: (count: number) => `${count} con confidenza troppo bassa`,
    noActionTitle: "Tutto sotto controllo",
    noActionBody: "Nessuna decisione richiede la tua attenzione in questo momento.",
    actionRequiredHeading: "Decisioni di oggi",
    moreDecisions: (count: number) => `+ ${count} altre decisioni`,
    reliabilityLabel: "Affidabilità",
    rankLabel: "Priorità",
  },
  errors: {
    propertyNotFound: "La struttura selezionata non è più disponibile.",
  },
  detail: {
    back: "← Oggi",
    statusOpen: "Aperta",
    statusResolved: "Risolta",
    detectedOn: (date: string) => `Rilevata il ${date}`,
    resolvedOn: (date: string) => `Risolta il ${date}`,
    episodeCount: (count: number) => `${count} episodi`,
    sectionCurrentState: "Stato attuale",
    sectionWhy: "Perché NINFA te lo mostra",
    sectionEvidence: "Evidenze",
    sectionHistory: "Evoluzione",
    reliabilityLabel: "Affidabilità",
    currentPriorityLine: (rank: number) => `Priorità #${rank} nell'analisi del giorno`,
    historyPriorityLine: (rank: number) => `Priorità #${rank}`,
    economicImpactLabel: "Impatto economico indicativo",
    evidenceActual: "Attuale",
    evidenceExpected: "Atteso",
    evidenceDelta: "Scostamento",
    evidenceCoverage: (percent: string) => `Copertura dati ${percent}`,
    evidenceComparablePeriods: (count: number) => `Basato su ${count} periodi comparabili`,
    loadErrorGeneric: "Non siamo riusciti a caricare la decisione.",
    retry: "Riprova",
    notFoundTitle: "Decisione non disponibile",
    notFoundBody: "Questa decisione non è disponibile per la struttura selezionata.",
    backToOggi: "Torna a Oggi",
    historyEmpty: "Nessuna evoluzione disponibile.",
    historyLoadMore: "Mostra eventi precedenti",
    historyLoadingMore: "Caricamento…",
    historyLoadMoreError: "Non siamo riusciti a caricare altri eventi. Riprova.",
  },
} as const;

/** `Decision.status` (OPEN/RESOLVED) - "Aperta" never implies "you must act", only that the
 * underlying problem has not been automatically resolved yet (see ADR 0021, "status is not a
 * recommendation"). */
export function decisionStatusCopy(status: DecisionStatus): string {
  return status === "OPEN" ? copy.detail.statusOpen : copy.detail.statusResolved;
}

/**
 * One Observation's lifecycle event, in Italian, calm and never alarmist. `NO_STATE_CHANGE`
 * reads differently depending on the detector's OWN source status - "no new conclusion" is not
 * a technical error, and is worded as such (see docs/architecture/decision-detail-ui-v1.md,
 * "Decision Memory").
 */
export function lifecycleEventCopy(transition: LifecycleTransition, sourceStatus: SourceStatus): string {
  switch (transition) {
    case "OPENED":
      return "Rilevata";
    case "OBSERVED":
      return "Ancora presente";
    case "RESOLVED":
      return "Risolta";
    case "REOPENED":
      return "Ricomparsa";
    case "NO_STATE_CHANGE":
      switch (sourceStatus) {
        case "INSUFFICIENT_DATA":
          return "Dati non sufficienti per una nuova conclusione";
        case "SUPPRESSED_LOW_CONFIDENCE":
          return "Nessuna nuova conclusione affidabile";
        case "NOT_APPLICABLE":
          return "Controllo non applicabile";
        default:
          return "Nuova valutazione";
      }
  }
}

/** Static, human titles per decision_type - NEVER AI-generated, NEVER a recommendation (see
 * docs/architecture/oggi-ui-v1.md, "Decision cards" - problem + evidence, not advice). */
export const decisionTypeTitles: Record<DecisionType, string> = {
  REV_PICKUP_LOW: "Pickup sotto le attese",
  REV_OCCUPANCY_RISK: "Rischio occupazione",
  REV_OTA_DEPENDENCY: "Dipendenza OTA",
  COST_CPOR_ANOMALY: "Costo per camera anomalo",
  LABOR_OVERSTAFFING: "Ore di personale sopra l'atteso",
};
