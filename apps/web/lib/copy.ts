import type {
  AnalysisDomain,
  DecisionStatus,
  DecisionType,
  LifecycleTransition,
  SourceStatus,
} from "@ninfa/contracts";

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
    // "Struttura attiva", not "Struttura": the sidebar has its own (future) "Struttura" section.
    selectorLabel: "Struttura attiva",
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
    // Gate 24B: this body line is now used ONLY for "ran before, just not today yet" (a prior
    // successful run exists) - `notProcessedNeverAnalyzed` below covers the OTHER real meaning
    // of NOT_PROCESSED ("this property has never been analysed, ever"). Neither line may claim
    // WHY today itself has no run (no "l'analisi di oggi è fallita" wording anywhere): a failed
    // run is never persisted, so it is indistinguishable from "not yet run" - see
    // docs/architecture/pilot-readiness-v1.md.
    notProcessedBody: "NINFA non ha ancora completato l'analisi per oggi.",
    notProcessedNeverAnalyzed: "NINFA non ha ancora completato una prima analisi.",
    lastSuccessfulAnalysis: (businessDate: string) =>
      `L'ultima analisi completata risale al ${businessDate}.`,
    dataQualityTitle: "Analisi parziale",
    dataQualityBody:
      "Alcuni controlli non dispongono ancora di dati sufficienti. NINFA non mostra conclusioni incerte.",
    dataQualityInsufficientCount: (count: number) => `${count} in attesa di dati sufficienti`,
    dataQualitySuppressedCount: (count: number) => `${count} con confidenza troppo bassa`,
    noActionTitle: "Tutto sotto controllo",
    noActionBody: "Nessuna decisione richiede la tua attenzione in questo momento.",
    // Gate 22: additive to every state above - qualifies "Tutto sotto controllo"/"Analisi
    // parziale" without ever implying every area was checked when it was not (see
    // docs/architecture/analysis-coverage-v1.md, "Semantica 'Tutto sotto controllo'").
    coveragePartial: (domains: string) => `Non analizzati: ${domains}.`,
    coverageUnknown: "Copertura dell'analisi non disponibile per questo run.",
    // Gate 23B: additive to every processed state above (never NOT_PROCESSED) - a plain FACT,
    // never a judgement. "Ultimo import prenotazioni", NEVER "Prenotazioni aggiornate al ...":
    // ImportJob.finished_at proves when NINFA finished importing, not up to which business date
    // the file's content was actually current (see
    // docs/architecture/booking-freshness-provenance-v1.md).
    freshnessKnown: (formatted: string) => `Ultimo import prenotazioni: ${formatted}.`,
    freshnessUnknown:
      "Informazione sull'ultimo import prenotazioni non disponibile per questo run.",
    actionRequiredHeading: "Decisioni di oggi",
    moreDecisions: (count: number) => `+ ${count} altre decisioni`,
    reliabilityLabel: "Affidabilità",
    rankLabel: "Priorità",
  },
  // Home UI V1: the sidebar. Dati / Struttura / Impostazioni do not exist yet - they are shown in the
  // approved layout, but never as a link to a page that is not there (see `AppSidebar`).
  nav: {
    skipToContent: "Vai al contenuto",
    mainLabel: "Navigazione principale",
    secondaryLabel: "Account e impostazioni",
    today: "Oggi",
    decisions: "Decisioni",
    data: "Dati",
    structure: "Struttura",
    settings: "Impostazioni",
    profile: "Profilo e account",
    comingSoon: "In arrivo",
    logoHome: "NINFA - vai a Oggi",
  },
  decisioni: {
    heading: "Decisioni",
  },
  // Home UI V1: "Oggi" - the decision-first home. Every string here is a TEMPLATE: no property name,
  // person, count, time or Decision text from the approved reference is ever hardcoded.
  home: {
    // `firstName === null` (no display name, or a blank one): "Ciao," - never derived from the email.
    greeting: (firstName: string | null) => (firstName === null ? "Ciao," : `Ciao ${firstName},`),
    decisionsRequireAttention: (count: number) =>
      count === 1 ? "1 decisione richiede attenzione" : `${count} decisioni richiedono attenzione`,
    // Gate 23B: a plain FACT about when NINFA finished an import - never "Dati aggiornati alle ...".
    freshnessKnown: (formatted: string) => `Ultimo import prenotazioni: ${formatted}`,
    freshnessUnknown: "Ultimo import prenotazioni non disponibile",
    freshnessToday: (time: string) => `oggi alle ${time}`,
    freshnessYesterday: (time: string) => `ieri alle ${time}`,
    refresh: "Aggiorna analisi",
    refreshing: "Aggiornamento in corso",
    domainSummaryLabel: "Riepilogo per area",
    // Tone words only for assistive tech: a tile never relies on its dot colour alone.
    attention: (count: number) => (count === 1 ? "1 attenzione" : `${count} attenzioni`),
    noAttention: "Nessuna attenzione",
    partialAnalysis: "Analisi parziale",
    unavailable: "Non disponibile",
  },
  errors: {
    propertyNotFound: "La struttura selezionata non è più disponibile.",
  },
  detail: {
    back: "← Decisioni",
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
    backToDecisioni: "Torna alle Decisioni",
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

/** Plain-language labels for the four Gate 22 analysis domains - a client NEVER renders
 * `AnalysisDomain`'s own raw values ("REVENUE", "COSTS", ...) in the UI. Home UI V1 renamed
 * DISTRIBUTION from "Canali" to "Distribuzione" (the approved reference's own word). */
export const analysisDomainLabels: Record<AnalysisDomain, string> = {
  REVENUE: "Ricavi",
  DISTRIBUTION: "Distribuzione",
  COSTS: "Costi",
  LABOR: "Personale",
};

/** "Not analysed", agreeing with each domain's own grammatical gender/number (the approved Home
 * reference itself writes "Non analizzati" under Costi and "Non analizzato" under Personale) - one
 * string per domain, never a single reused form. */
export const domainNotAnalyzedCopy: Record<AnalysisDomain, string> = {
  REVENUE: "Non analizzati",
  DISTRIBUTION: "Non analizzata",
  COSTS: "Non analizzati",
  LABOR: "Non analizzato",
};
