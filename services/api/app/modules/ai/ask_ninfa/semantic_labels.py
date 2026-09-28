"""Gate 19.1: the ONE place that turns NINFA's own internal engine vocabulary - `decision_type`,
`DecisionStatus`, `LifecycleTransition`/`SourceStatus`, `ActionCode`, `RiskNote`, `CostCategory`,
`LaborCategory`, and every whitelisted `facts_payload`/`evidence_payload` key - into the Italian,
user-safe phrases `AskDecisionContextBuilder` hands to a language model provider.

INTERNAL CODES STAY INTERNAL: nothing downstream of this module ever sees the raw StrEnum value or
raw JSON key again for the fields it covers. Every mapping here is EXPLICIT and hand-audited against
the real enums/whitelists it translates (`app.modules.decisions.whitelist`,
`app.modules.recommendations.types`) - never a blind regex over the raw payload, never a generic
"humanize this snake_case key" heuristic that could accidentally produce a plausible-looking but
wrong label. A key with no entry below is DROPPED, never passed through raw (see
`data_points_of`) - the same fail-safe posture `apps/web/lib/recommendations/copy.ts`'s
`primaryActionCopyOf` already established for an unrecognised `action_code`.

Wherever the real product UI already ships an Italian phrase for the same concept (Gate 15's
`decision-card.tsx`, Gate 17's `recommendation-ui-v1` copy, `apps/web/lib/copy.ts`), this module
reuses the EXACT same wording, so a user reads the same term in the UI and in an Ask NINFA answer -
never two different translations of the same fact. See ADR 0026 for the "why" behind this file
existing as a structural boundary rather than a prompt-only instruction.
"""

from app.modules.decisions.types import DecisionStatus, LifecycleTransition, SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory
from app.modules.recommendations.types import ActionCode, RiskNote

from .types import AskDataPoint, ContextValue

# --- decision_type -> Italian title -----------------------------------------------------------
# The SAME wording `apps/web/lib/copy.ts`'s `decisionTypeTitles` already ships - one vocabulary,
# never two translations of the same decision_type.
DECISION_TYPE_LABELS: dict[PriorityDecisionType, str] = {
    PriorityDecisionType.REV_PICKUP_LOW: "Pickup sotto le attese",
    PriorityDecisionType.REV_OCCUPANCY_RISK: "Rischio occupazione",
    PriorityDecisionType.REV_OTA_DEPENDENCY: "Dipendenza OTA",
    PriorityDecisionType.COST_CPOR_ANOMALY: "Costo per camera anomalo",
    PriorityDecisionType.LABOR_OVERSTAFFING: "Ore di personale sopra l'atteso",
}


def decision_label_of(decision_type: PriorityDecisionType) -> str:
    return DECISION_TYPE_LABELS[decision_type]


# --- Decision.status -> Italian ---------------------------------------------------------------
# The SAME wording `apps/web/lib/copy.ts`'s `decisionStatusCopy` already ships.
_DECISION_STATUS_LABELS: dict[DecisionStatus, str] = {
    DecisionStatus.OPEN: "Aperta",
    DecisionStatus.RESOLVED: "Risolta",
}


def decision_status_label_of(status: DecisionStatus) -> str:
    return _DECISION_STATUS_LABELS[status]


# --- one Observation's own lifecycle event -> Italian -------------------------------------------
# The SAME wording `apps/web/lib/copy.ts`'s `lifecycleEventCopy` already ships - `NO_STATE_CHANGE`
# reads differently depending on the detector's OWN source status, exactly like that function.
_LIFECYCLE_EVENT_LABELS: dict[LifecycleTransition, str] = {
    LifecycleTransition.OPENED: "Rilevata",
    LifecycleTransition.OBSERVED: "Ancora presente",
    LifecycleTransition.RESOLVED: "Risolta",
    LifecycleTransition.REOPENED: "Ricomparsa",
}

_NO_STATE_CHANGE_LABELS: dict[SourceStatus, str] = {
    SourceStatus.INSUFFICIENT_DATA: "Dati non sufficienti per una nuova conclusione",
    SourceStatus.SUPPRESSED_LOW_CONFIDENCE: "Nessuna nuova conclusione affidabile",
    SourceStatus.NOT_APPLICABLE: "Controllo non applicabile",
}


def observation_status_label_of(
    transition: LifecycleTransition, source_status: SourceStatus
) -> str:
    if transition is not LifecycleTransition.NO_STATE_CHANGE:
        return _LIFECYCLE_EVENT_LABELS[transition]
    return _NO_STATE_CHANGE_LABELS.get(source_status, "Nuova valutazione")


# --- cost/labor category -> Italian -------------------------------------------------------------
_COST_CATEGORY_LABELS: dict[CostCategory, str] = {
    CostCategory.PERSONNEL: "Personale",
    CostCategory.LAUNDRY: "Lavanderia",
    CostCategory.CLEANING: "Pulizie",
    CostCategory.AMENITIES: "Forniture per gli ospiti",
    CostCategory.FOOD: "Alimenti",
    CostCategory.BEVERAGE: "Bevande",
    CostCategory.UTILITIES: "Utenze",
    CostCategory.MAINTENANCE: "Manutenzione",
    CostCategory.SOFTWARE: "Software",
    CostCategory.MARKETING: "Marketing",
    CostCategory.OTA_COMMISSIONS: "Commissioni OTA",
    CostCategory.PROFESSIONAL_SERVICES: "Servizi professionali",
    CostCategory.TRANSPORT: "Trasporti",
    CostCategory.OTHER: "Altro",
}

_LABOR_CATEGORY_LABELS: dict[LaborCategory, str] = {
    LaborCategory.HOUSEKEEPING: "Housekeeping",
    LaborCategory.FRONT_OFFICE: "Ricevimento",
    LaborCategory.FOOD_BEVERAGE: "Sala e bar",
    LaborCategory.KITCHEN: "Cucina",
    LaborCategory.MAINTENANCE: "Manutenzione",
    LaborCategory.MANAGEMENT: "Direzione",
    LaborCategory.SPA_WELLNESS: "Spa e benessere",
    LaborCategory.OTHER: "Altro",
}


def cost_category_label_of(category: CostCategory) -> str:
    return _COST_CATEGORY_LABELS[category]


def labor_category_label_of(category: LaborCategory) -> str:
    return _LABOR_CATEGORY_LABELS[category]


# --- Recommendation ActionCode -> Italian title/description --------------------------------------
# The SAME wording `apps/web/lib/recommendations/copy.ts`'s `PRIMARY_ACTION_COPY` already ships for
# every primary action - one vocabulary, never a second translation that could drift from the UI.
_PRIMARY_ACTION_TITLE: dict[ActionCode, str] = {
    ActionCode.REVIEW_PRICING_AND_AVAILABILITY: "Rivedi prezzi e disponibilità",
    ActionCode.REVIEW_DEMAND_POSITIONING: "Rivedi il posizionamento della data",
    ActionCode.REVIEW_DISTRIBUTION_MIX: "Rivedi il mix distributivo",
    ActionCode.REVIEW_COST_DRIVERS: "Verifica cosa sta incidendo sui costi",
    ActionCode.REVIEW_STAFFING_PLAN: "Rivedi la pianificazione delle ore",
}

_PRIMARY_ACTION_DESCRIPTION: dict[ActionCode, str] = {
    ActionCode.REVIEW_PRICING_AND_AVAILABILITY: (
        "Verifica se prezzi, disponibilità e restrizioni sono coerenti con l'andamento della data."
    ),
    ActionCode.REVIEW_DEMAND_POSITIONING: (
        "Valuta se il posizionamento della data rispetto alla domanda prevista è ancora coerente."
    ),
    ActionCode.REVIEW_DISTRIBUTION_MIX: (
        "Valuta se la distribuzione tra i canali è coerente con l'andamento osservato."
    ),
    ActionCode.REVIEW_COST_DRIVERS: (
        "Verifica quali fattori stanno contribuendo allo scostamento di costo rilevato."
    ),
    ActionCode.REVIEW_STAFFING_PLAN: (
        "Verifica se la pianificazione delle ore è coerente con il carico di lavoro previsto."
    ),
}

# The SAME wording `apps/web/lib/recommendations/copy.ts`'s `SUPPORTING_ACTION_LABEL` already ships
# for every supporting check - a single short label, never a second, invented sentence (the real
# UI does not have one either - see `AskActionContext.description`'s own docstring).
_SUPPORTING_ACTION_TITLE: dict[ActionCode, str] = {
    ActionCode.CHECK_CHANNEL_VISIBILITY: "Verifica la visibilità sui canali",
    ActionCode.CHECK_BOOKING_RESTRICTIONS: "Verifica le restrizioni di prenotazione",
    ActionCode.CHECK_PRICING: "Verifica i prezzi",
    ActionCode.CHECK_AVAILABILITY_AND_RESTRICTIONS: "Verifica disponibilità e restrizioni",
    ActionCode.CHECK_DIRECT_CHANNEL_AVAILABILITY: "Verifica la disponibilità sul canale diretto",
    ActionCode.CHECK_DISTRIBUTION_CONFIGURATION: "Verifica la configurazione della distribuzione",
    ActionCode.CHECK_RECENT_COST_ENTRIES: "Verifica le registrazioni di costo recenti",
    ActionCode.CHECK_VOLUME_VS_COST: "Verifica il rapporto tra volumi e costi",
    ActionCode.CHECK_SHIFT_COVERAGE: "Verifica la copertura dei turni",
    ActionCode.CHECK_SCHEDULED_HOURS: "Verifica le ore programmate",
}

# The SAME wording `apps/web/lib/recommendations/copy.ts`'s `RISK_NOTE_COPY` already ships.
_RISK_NOTE_TEXT: dict[RiskNote, str] = {
    RiskNote.PRICING_CHANGE_MAY_AFFECT_REVENUE: (
        "Le variazioni di prezzo possono incidere sui ricavi."
    ),
    RiskNote.STAFFING_CHANGE_MAY_AFFECT_SERVICE: (
        "Le variazioni di personale possono incidere sul livello di servizio."
    ),
    RiskNote.DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY: (
        "Le variazioni distributive possono incidere sulla visibilità."
    ),
}


def primary_action_title_of(action_code: ActionCode) -> str:
    return _PRIMARY_ACTION_TITLE[action_code]


def primary_action_description_of(action_code: ActionCode) -> str:
    return _PRIMARY_ACTION_DESCRIPTION[action_code]


def supporting_action_title_of(action_code: ActionCode) -> str:
    return _SUPPORTING_ACTION_TITLE[action_code]


def risk_note_text_of(note: RiskNote) -> str:
    return _RISK_NOTE_TEXT[note]


# --- facts/evidence: raw whitelisted key -> (Italian label, unit) --------------------------------
# Reuses, wherever one already exists, the EXACT wording Gate 15's `decision-card.tsx` already
# ships for the same fact (`"forecast_rooms" -> "Previsione camere"`, etc.) - the rest are new,
# hand-picked labels for facts the card summary does not render but Ask NINFA's richer context
# benefits from. A key with NO entry here is intentionally DROPPED (see `context_builder.py`'s
# `_data_points_of`) - almost always because it is an internal detector CONDITION flag
# (`percent_condition`, `gap_condition`, `structural_condition`'s own upper-fence threshold, ...)
# that the numeric facts already surrounding it make redundant to spell out separately, or a pure
# technical/versioning value (`rules_version`) with zero explanatory content for a user.
_Spec = tuple[str, str | None]  # (label, unit)

FACT_LABELS: dict[PriorityDecisionType, dict[str, _Spec]] = {
    PriorityDecisionType.REV_PICKUP_LOW: {
        "current_rooms_on_books": ("Camere prenotate", "camere"),
        "rooms_available": ("Camere disponibili", "camere"),
        "lead_time_days": ("Anticipo rispetto al soggiorno", "giorni"),
        "actual_pickup": ("Pickup rilevato", "camere"),
        "expected_pickup": ("Pickup atteso", "camere"),
        "delta_rooms": ("Scostamento", "camere"),
        "missing_rooms": ("Camere mancanti", "camere"),
        "delta_percent_exact": ("Scostamento percentuale", "%"),
    },
    PriorityDecisionType.REV_OCCUPANCY_RISK: {
        "current_rooms_on_books": ("Camere prenotate", "camere"),
        "rooms_available": ("Camere disponibili", "camere"),
        "lead_time_days": ("Anticipo rispetto al soggiorno", "giorni"),
        "forecast_rooms": ("Previsione camere", "camere"),
        "expected_final_rooms": ("Atteso a fine finestra", "camere"),
        "occupancy_gap_pp_exact": ("Scarto occupazione", "punti percentuali"),
        "room_shortfall": ("Scarto camere", "camere"),
    },
    PriorityDecisionType.REV_OTA_DEPENDENCY: {
        "window_start": ("Inizio periodo osservato", None),
        "window_end": ("Fine periodo osservato", None),
        "window_days": ("Durata del periodo", "giorni"),
        "ota_room_nights": ("Notti-camera su OTA", "notti"),
        "direct_room_nights": ("Notti-camera dirette", "notti"),
        "ota_share_exact": ("Quota OTA", "%"),
        "expected_ota_share_exact": ("Quota attesa", "%"),
        "delta_pp_exact": ("Scostamento", "punti percentuali"),
        "structural_condition": ("Dipendenza strutturale", None),
        "rising_condition": ("In aumento", None),
    },
    PriorityDecisionType.COST_CPOR_ANOMALY: {
        "target_period_end": ("Fine periodo", None),
        "actual_cpor_exact": ("Costo per camera", None),
        "expected_cpor_exact": ("Costo atteso per camera", None),
        "delta_cpor_exact": ("Scostamento", None),
        "delta_percent_exact": ("Scostamento percentuale", "%"),
    },
    PriorityDecisionType.LABOR_OVERSTAFFING: {
        "forecast_rooms_exact": ("Previsione camere", "camere"),
        "scheduled_hours_exact": ("Ore programmate", "ore"),
        "expected_labor_hours_exact": ("Ore attese", "ore"),
        "excess_hours_exact": ("Ore in eccesso", "ore"),
        "delta_percent_exact": ("Scostamento percentuale", "%"),
    },
}

# Economic-proxy-shaped evidence values get a label that ALREADY carries the "stima indicativa"
# caveat (ADR 0026, "why the economic proxy caveat remains") - never the raw field name, and never
# presented as a certain figure even before the system instructions' own rule #7 reinforces it.
_INDICATIVE_ESTIMATE = "stima indicativa, non un valore certo"

EVIDENCE_LABELS: dict[PriorityDecisionType, dict[str, _Spec]] = {
    PriorityDecisionType.REV_PICKUP_LOW: {
        "baseline_confidence": ("Affidabilità della base storica", "%"),
        "pattern_confidence": ("Affidabilità del pattern storico", "%"),
        "pattern_pair_count": ("Confronti storici usati", "confronti"),
        "revenue_gap_proxy": (f"Impatto sui ricavi ({_INDICATIVE_ESTIMATE})", None),
        "reference_adr": ("Tariffa media di riferimento", None),
    },
    PriorityDecisionType.REV_OCCUPANCY_RISK: {
        "baseline_confidence": ("Affidabilità della base storica", "%"),
        "pattern_confidence": ("Affidabilità del pattern storico", "%"),
        "pattern_pair_count": ("Confronti storici usati", "confronti"),
        "revenue_gap_proxy": (f"Impatto sui ricavi ({_INDICATIVE_ESTIMATE})", None),
        "reference_adr": ("Tariffa media di riferimento", None),
    },
    PriorityDecisionType.REV_OTA_DEPENDENCY: {
        "classification_coverage_pct_exact": ("Copertura della classificazione canali", "%"),
        "observed_day_count": ("Giorni con dati osservati", "giorni"),
        "reconstructed_day_count": ("Giorni con dati ricostruiti", "giorni"),
        "sample_count": ("Osservazioni storiche usate", "osservazioni"),
        "baseline_confidence": ("Affidabilità della base storica", "%"),
        "ota_room_revenue_exposure": (f"Ricavo esposto su OTA ({_INDICATIVE_ESTIMATE})", None),
    },
    PriorityDecisionType.COST_CPOR_ANOMALY: {
        "classification_coverage_pct_exact": ("Copertura della classificazione", "%"),
        "occupancy_provenance_score_exact": ("Affidabilità dei dati di occupazione", "%"),
        "sample_count": ("Periodi usati nel confronto", "periodi"),
        "observed_period_count": ("Periodi con dati osservati", "periodi"),
        "baseline_confidence": ("Affidabilità della base storica", "%"),
    },
    PriorityDecisionType.LABOR_OVERSTAFFING: {
        "classification_coverage_pct_exact": ("Copertura della classificazione", "%"),
        "demand_confidence": ("Affidabilità della previsione di domanda", "%"),
        "sample_count": ("Giorni usati nel confronto", "giorni"),
        "fully_observed_count": ("Giorni con dati completi", "giorni"),
        "labor_cost_gap_proxy_exact": (
            f"Impatto sui costi del personale ({_INDICATIVE_ESTIMATE})",
            None,
        ),
    },
}


def _stringify(value: ContextValue) -> str:
    if isinstance(value, bool):
        return "Sì" if value else "No"
    return str(value)


def data_points_of(
    specs: dict[str, _Spec], payload: dict[str, ContextValue]
) -> tuple[AskDataPoint, ...]:
    """Iterates `specs` IN ITS OWN DEFINED ORDER (never the raw payload's own, arbitrary JSON key
    order) so the same decision type always produces a deterministically-ordered context. A key
    present in `payload` but absent from `specs` is silently DROPPED - the fail-safe default for
    anything this module was not explicitly audited to explain (see this module's own docstring)."""
    points = []
    for key, (label, unit) in specs.items():
        if key not in payload:
            continue
        value = payload[key]
        points.append(AskDataPoint(label=label, value=_stringify(value), unit=unit))
    return tuple(points)


__all__ = [
    "DECISION_TYPE_LABELS",
    "EVIDENCE_LABELS",
    "FACT_LABELS",
    "cost_category_label_of",
    "data_points_of",
    "decision_label_of",
    "decision_status_label_of",
    "labor_category_label_of",
    "observation_status_label_of",
    "primary_action_description_of",
    "primary_action_title_of",
    "risk_note_text_of",
    "supporting_action_title_of",
]
