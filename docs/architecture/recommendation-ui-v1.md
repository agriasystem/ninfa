# Recommendation UI V1 (`recommendation-ui-v1`, Gate 17)

Gate 16 exposed a deterministic, non-AI `recommendation` on the Decision Detail API - additive,
read-only, `requires_human_review` always `true` - but no frontend page rendered it yet. This gate
is the other half of that promise (ADR 0021, point 16; ADR 0022, point 16): one new, additive
section, "Cosa puoi valutare", on Gate 15's own Decision Detail page. See ADR 0023 for the "why"
behind every choice below; this document is the "what" and "how".

## Scope

Frontend only. No backend file changes, no new route, no new query parameter, no new dependency.
`recommendation` already arrives inside the existing `GET /decisions/{decisionId}` response Gate 15
already fetches - this gate adds a typed client for it (`packages/contracts`) and one new,
additive React section, nothing else. The Oggi feed, the decision cards, the history/timeline and
the login/property-selector pages are untouched: none of their contracts (`FeedItemResponse`,
`ObservationDetail`) carry a `recommendation` field at all, so there is no code path anywhere in
those surfaces that could render one, even by accident.

## Placement

Inside `DecisionDetailContent` (`components/decision-detail-view.tsx`), as a fifth, additive
section, always after Evidenze and always before `DecisionTimeline` ("Evoluzione"):

    Header → Stato attuale → Perché NINFA te lo mostra → Evidenze → Cosa puoi valutare → Evoluzione

The user sees the problem and the evidence behind it FIRST; the recommendation is what to look at
next, never what opens the page. There is no code path that could render the recommendation before
the evidence - it is a single, fixed section in `DecisionDetailContent`'s own JSX, not a
conditionally-reordered one.

## The question this section answers

"Cosa posso valutare adesso?" - never "cosa devo fare?". NINFA proposes a verification or a
direction; the user decides. The heading itself is "Cosa puoi valutare", never "Azioni da fare",
"Devi fare", "Intervento consigliato" or "Soluzione".

## Recommendation states

The UI reacts to `recommendation.status` exactly as the backend defines it - never re-derived from
`Decision.status` or `latest_observation.source_status` directly:

| Status | UI |
| --- | --- |
| `AVAILABLE` | The full section: primary action, up to 2 supporting checks, risk notes (if any), a human-review note. |
| `NOT_AVAILABLE` | Nothing. The section does not render at all - not an empty state, not a placeholder. |
| anything else (including a status this frontend does not recognise) | Nothing - same as `NOT_AVAILABLE`, a deliberate fail-safe default (see ADR 0023, "why NOT_AVAILABLE is hidden"). |
| `INSUFFICIENT_CONTEXT` | A discreet section with one neutral sentence, no primary action, no supporting checks, no risk notes. |

`recommendationViewModel()` (`lib/recommendations/view-model.ts`) is the one place this decision is
made; `RecommendationPanel` (`components/recommendation-panel.tsx`) only renders whatever that pure
function returned.

## Copy: ActionCode, never DecisionType

`lib/recommendations/copy.ts` maps the backend's own closed `action_code`/`risk_notes` vocabulary
(Gate 16's `ActionCode`/`RiskNote`) to static Italian strings - a `Map<string, ...>` per concept
(primary action title+description, supporting-check label, risk-note sentence), each returning
`null` for anything it does not recognise. The Recommendation Engine (Gate 16's `rules.py`) remains
the sole source of truth for WHICH action was chosen; this module never branches on
`decision_type`, and could not even if it tried - `RecommendationResponse` carries no
`decision_type` field at all.

### The five primary actions

| `decision_type` (Gate 16's own mapping) | `action_code` | Italian title |
| --- | --- | --- |
| `REV_PICKUP_LOW` | `REVIEW_PRICING_AND_AVAILABILITY` | "Rivedi prezzi e disponibilità" |
| `REV_OCCUPANCY_RISK` | `REVIEW_DEMAND_POSITIONING` | "Rivedi il posizionamento della data" |
| `REV_OTA_DEPENDENCY` | `REVIEW_DISTRIBUTION_MIX` | "Rivedi il mix distributivo" |
| `COST_CPOR_ANOMALY` | `REVIEW_COST_DRIVERS` | "Verifica cosa sta incidendo sui costi" |
| `LABOR_OVERSTAFFING` | `REVIEW_STAFFING_PLAN` | "Rivedi la pianificazione delle ore" |

Every string uses "rivedi"/"verifica"/"valuta"/"controlla" - never "riduci"/"abbassa"/"chiudi"/
"elimina"/"licenzia"/"sostituisci", checked directly by a safety-copy test scanning every real
primary/supporting/risk-note string this module can ever produce
(`lib/recommendations/view-model.test.ts`, `components/recommendation-panel.test.tsx`).

### Supporting checks ("Da verificare")

At most 2 (the backend's own `MAX_SUPPORTING_CHECKS`), in the backend's own order, never reordered,
never padded. An `action_code` this frontend has no copy for is silently dropped, never shown as a
raw enum. Rendered as a plain `<ul>` - no checkbox, because there is no persisted "done" state for
any of these (Gate 16 recomputes the recommendation fresh on every request; a checked box would be
a lie the instant the page reloads).

### Risk notes ("Da tenere presente")

Read only from `primary_action.risk_notes` (the only place Gate 16's rules ever set a non-empty
one), mapped through the same fail-safe `Map` pattern. Neutral, factual sentences - never a
red/critical alert, never a numeric or bucketed risk score (`Alta`/`Media`/`Bassa` does not exist
here either, matching the same discipline the confidence hotfix already established for the
Evidenze section).

### Human-review note

One sentence, shown once, only for a real `AVAILABLE` recommendation - never repeated per
supporting check, never shown for `INSUFFICIENT_CONTEXT` (there is nothing yet to ask a human to
weigh in on): "Valuta questa indicazione nel contesto operativo della tua struttura."

## Confidence is not repeated here

Gate 16 copies `confidence` from the same observation the Evidenze section already displays as
"Affidabilità N%" (correct since the confidence display hotfix, `fix/frontend-confidence-display`).
`RecommendationPanel` never reads `recommendation.confidence` at all -
`recommendationViewModel()`'s return type does not even carry the field - so there is no second,
independent formatting of the same number, and no way for this section to ever reintroduce the
`*100` class of bug the hotfix fixed.

## No mutation, no execution, structurally

`RecommendationPanel` takes exactly one prop (`recommendation: RecommendationResponse`) and no
callback of any kind - there is nothing here that COULD wire up an execute/approve/apply handler.
No `<button>`, no `<input>`, no `role="button"`/`role="checkbox"` exists anywhere inside
`.recommendation-panel`, checked directly
(`components/recommendation-panel.test.tsx`, `components/decision-detail-view.test.tsx`). The
primary action is plain text (a title + a description), never a button.

## Visual design

A soft, controlled accent (`--color-accent-soft`, the same token this app's own design system
already reserves for a gentle highlight), a thin border, no gradient, no glow, no "AI" iconography
(no sparkles, no robot, no magic wand) - a review prompt, not "AI magic". Distinguishable from the
Evidenze panel above it (which uses the plain `--color-surface` white), but never more visually
dominant than the problem it is about.

## Responsive / accessibility

A real `<h2>` heading, `<ul>` for supporting checks and risk notes, no colour-only meaning, no
focus management needed (nothing here is interactive). Verified by hand at
1440×900/1024×768/390×844, the same three viewports and the same "no browser-automation tool in
this repository" posture Gate 14/15 already established - the section collapses to the same
single-column, capped-width reading layout the rest of the page already uses, with reduced padding
under 480px matching `.decision-detail__evidence`'s own breakpoint.

## Loading / error handling

None added. The recommendation arrives inside the SAME Decision Detail fetch Gate 15 already makes
- no second request, no independent skeleton, no independent error state. A Decision Detail load
failure behaves exactly as it did before this gate.

## Source status semantics (unchanged from Gate 16, now visible)

- RESOLVED/CLEAR → `NOT_AVAILABLE` → section absent.
- OPEN with a non-TRIGGERED latest observation (INSUFFICIENT_DATA/SUPPRESSED_LOW_CONFIDENCE/
  NOT_APPLICABLE) → `NOT_AVAILABLE` → section absent, regardless of `Decision.status` staying OPEN.
- REOPENED with a TRIGGERED latest observation → `AVAILABLE` again, built from THAT observation's
  own facts only - the UI never compares against a prior episode's recommendation, because Gate 16
  does not persist recommendation history at all.

## Limitations (intentional, documented debt)

- No recommendation history/audit UI - Gate 16 persists nothing, so there is nothing to show for a
  past episode; only the CURRENT recommendation is ever visible.
- No Ask NINFA, no chat, no AI-generated prose - explicitly out of scope (ADR 0021/0022, point 16;
  ADR 0023, "Ask NINFA future integration").
- No dedicated E2E/browser-automation suite - same posture as Gate 14/15: a manual visual checklist
  at the three target viewports, plus component/golden tests using the real Gate 16 API shape.
- No Recommendation surface anywhere except Decision Detail - not on a card, not on the feed, not
  in the history timeline, not on login/property-selection.
