import type { DecisionType } from "@ninfa/contracts";

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
} as const;

/** Static, human titles per decision_type - NEVER AI-generated, NEVER a recommendation (see
 * docs/architecture/oggi-ui-v1.md, "Decision cards" - problem + evidence, not advice). */
export const decisionTypeTitles: Record<DecisionType, string> = {
  REV_PICKUP_LOW: "Pickup sotto le attese",
  REV_OCCUPANCY_RISK: "Rischio occupazione",
  REV_OTA_DEPENDENCY: "Dipendenza OTA",
  COST_CPOR_ANOMALY: "Costo per camera anomalo",
  LABOR_OVERSTAFFING: "Ore di personale sopra l'atteso",
};
