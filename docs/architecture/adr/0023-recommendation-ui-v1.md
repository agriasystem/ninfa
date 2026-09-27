# 0023 — Recommendation UI V1: a review prompt, never a decision

## Context

Gate 16 (ADR 0022) built the Recommendation Engine: a deterministic, non-AI derivation over
Gate 11's own Decision Memory, exposed additively on Gate 12's Decision Detail API, with
`requires_human_review = true` unconditionally and no field anywhere that could mean "apply this
automatically". Nothing consumed it yet - ADR 0021 (point 16) and ADR 0022 (point 16) both named
this explicitly as future work: "when a Recommendation layer is built, it is a NEW section,
additive to this page, never a rewording of the evidence/why sections that already exist." This
gate is that page.

## Decision

1. **Evidence before recommendation, structurally, not just by convention.** `RecommendationPanel`
   is the fifth and LAST section inside `DecisionDetailContent`'s fixed JSX, after Evidenze -
   there is no conditional reordering, no code path that could move it earlier. The user reads the
   problem and the evidence behind it before NINFA offers anything to look at next.

2. **"Cosa puoi valutare", never "Cosa devo fare".** The section heading, and every string this
   frontend maps an `action_code` to, answers "what can I evaluate now", not "what must I do".
   NINFA proposes a verification or a direction; the user decides - the UI must never read as
   though NINFA already decided FOR them.

3. **Copy maps `action_code`, never `decision_type`.** `lib/recommendations/copy.ts` is keyed
   exclusively by the backend's own closed `ActionCode`/`RiskNote` vocabulary (Gate 16). The
   Recommendation Engine remains the sole authority for WHICH action was chosen for a given
   Decision; the frontend's only job is turning a closed code into Italian, the same relationship
   `decisionTypeTitles` already has with `decision_type`. `RecommendationResponse` does not even
   carry a `decision_type` field, so there is no way for a future contributor to accidentally
   branch on it here.

4. **`DecisionType` does not choose the action - structurally, not by discipline.** Because the
   view-model's only input is `RecommendationResponse` (no `decision_type` in scope at all), there
   is no code path in `lib/recommendations/*` that could special-case a decision type. The five
   real decision types happen to map one-to-one to five real primary `action_code`s (Gate 16's own
   `_RULE_BY_TYPE`), but that mapping lives entirely on the backend; the frontend never re-derives
   or checks it.

5. **`NOT_AVAILABLE` renders nothing, not an empty state.** A CLEAR/RESOLVED decision, or an OPEN
   decision whose latest observation is not TRIGGERED (INSUFFICIENT_DATA/SUPPRESSED_LOW_CONFIDENCE/
   NOT_APPLICABLE), has nothing to recommend RIGHT NOW - showing a stale prior recommendation, or an
   empty "Cosa puoi valutare" placeholder, would misrepresent what NINFA currently knows. This
   applies equally to any status the frontend does not recognise (a defensive default, exercised
   directly by `recommendationViewModel`'s own "unrecognised status" test): hidden is always the
   safe failure mode, never a guess.

6. **`INSUFFICIENT_CONTEXT` is shown explicitly, with neutral copy - it is not the same as
   `NOT_AVAILABLE`.** The latest observation IS genuinely TRIGGERED here; the problem is real and
   still being shown by the rest of the page. Hiding the section entirely would look identical to
   "nothing to review", which is a different, false claim. A single, calm sentence
   ("Non ci sono ancora elementi sufficienti per proporti una verifica affidabile.") is honest
   about what NINFA does and does not know, without inventing a fallback action or using
   error/failure language.

7. **No checkboxes - there is no persisted "done" state to check.** Gate 16 recomputes the
   recommendation fresh on every request and persists nothing; a checkbox implies a state the
   system does not keep, and would silently reset on the very next reload, which is worse than
   not offering the affordance at all. Supporting checks render as a plain `<ul>`.

8. **No execute/apply/approve/confirm/complete control anywhere, structurally.**
   `RecommendationPanel` takes exactly one prop and no callback - there is nothing here that COULD
   wire up a mutation. The primary action is rendered as plain text (a title and a description),
   never a `<button>`. A structural test scans the rendered DOM for `button`/`input`/
   `role="button"`/`role="checkbox"` inside `.recommendation-panel` and asserts none exist, for
   every real recommendation shape this frontend can produce.

9. **Risk notes are neutral sentences, never a red alert or a bucketed score.** The backend's own
   `RiskNote` enum is already a closed, factual vocabulary ("pricing changes may affect revenue");
   the frontend adds no severity, no colour-as-meaning, no `Alto`/`Medio`/`Basso` tier - the same
   discipline the confidence hotfix already established for "Affidabilità" (a raw fact, never a
   bucketed judgement).

10. **Confidence is not duplicated here.** The Evidenze section already shows
    "Affidabilità N%" from the same underlying observation Gate 16 copies its own `confidence`
    from. `recommendationViewModel()`'s return type carries no confidence field at all -
    `RecommendationPanel` cannot render it even by accident, and there is no second place the
    `*100` class of bug the confidence-display hotfix fixed could ever reappear.

11. **No recommendation history UI**, because Gate 16 persists none. Only the CURRENT
    recommendation (computed from the latest observation) is ever shown; there is no code path
    that could compare it against an earlier episode's, because no earlier one is retained anywhere
    to compare against.

12. **REOPENED with a TRIGGERED latest observation shows the current recommendation, built from
    THAT observation's own facts only.** The engine (Gate 16) already guarantees this at the data
    layer (`test_golden_reopened_recommendation_reflects_latest_observation_only`); the UI adds no
    additional logic here - it simply renders whatever `AVAILABLE` recommendation the API returned.

13. **No "AI magic" aesthetic.** A soft, controlled accent tint already used elsewhere in this
    design system, a thin border, no gradient, no glow, no sparkles/robot/magic-wand iconography.
    A deterministic, rule-based suggestion is not artificial intelligence, and the visual design
    must not imply otherwise - it should read as a calm, secondary prompt, never more visually
    dominant than the problem section above it.

14. **No new UI library, no new runtime dependency.** Plain semantic HTML/CSS, the same
    `--color-*`/`--space-*`/`--radius-*` design tokens and BEM-ish class naming every other
    component in this app already uses.

15. **Responsive and accessible by the same construction as Gate 15.** A real `<h2>` heading,
    `<ul>` lists, no colour-only meaning, no focus management needed (nothing here is
    interactive) - verified at the same three viewports (1440×900/1024×768/390×844), no
    Playwright, same as Gate 14/15's own posture.

16. **Ask NINFA remains explicitly future work.** This gate is a read-only presentation of a
    deterministic recommendation; a future conversational "Ask NINFA" layer, if built, would be a
    separate, additive surface with its own explicit scope decision, never implied by anything
    built here.

## Alternatives considered

- **Keying copy by `decision_type` instead of `action_code`.** Rejected: it would require the
  frontend to re-derive which action a given decision type gets, duplicating a decision the
  Recommendation Engine already made and risking the two disagreeing on a future rule change
  (e.g. a sixth decision type, or a primary action code changing for an existing one). Keying by
  `action_code` means the frontend only ever needs new copy when the ENGINE adds a new code, never
  when it changes an existing mapping.
- **A closed TypeScript union for `action_code`/`category`/`scope`/`status`.** Rejected in favour
  of plain `string` on the wire-level contract types, mirroring the backend's own Pydantic `str`
  fields exactly (unlike `target.type`, a real `Literal`-discriminated union the backend itself
  enforces). A closed union would either need an unsafe cast at the API boundary or silently permit
  values the type system claims are impossible; a plain `string` plus an explicit, testable
  fail-safe lookup is honest about what the contract actually guarantees.
- **Checkboxes for supporting checks, backed by client-side (browser-storage) "completed" state.**
  Rejected: that state would belong to the browser, not to NINFA - it would vanish on another
  device, another browser, or a cleared cache, creating a false sense of persistence for something
  the backend recomputes fresh every request.
- **Showing the last known recommendation when the current one is `NOT_AVAILABLE`.** Rejected -
  exactly the "stale recommendation" failure mode Gate 16's own engine was designed to prevent at
  the data layer (ADR 0022, point 5); the UI must not reintroduce it one layer up.
- **A confidence badge on the recommendation card itself.** Rejected: Gate 11/12 already expose the
  real percentage on the same page (Evidenze); a second rendering would be two sources of truth for
  one number, exactly the concern ADR 0022 already raised (and rejected a confidence TIER for the
  same reason) - and reformatting it a second time is exactly the surface the recent confidence
  scale hotfix (`fix/frontend-confidence-display`) had to fix once already.

## Consequences

- A sixth decision type (and its new primary `ActionCode`) requires new copy in
  `lib/recommendations/copy.ts` - `primaryActionCopyOf`/`supportingActionLabelOf` already fail safe
  (return `null`, rendered as nothing) until that copy is added, so a backend-only rollout never
  shows a raw enum or a broken section in the meantime.
- Any future `RiskNote` the backend adds is invisible in the UI (silently dropped) until
  `RISK_NOTE_COPY` gains an entry for it - a deliberate, safe default, not a bug to route around.
- A future Recommendation history/audit view, if ever built, is a wholly new feature: Gate 16
  persists nothing today, so there is no existing data model to extend, only a new one to design
  from scratch.
- A future Ask NINFA surface is additive, exactly like this gate was to Gate 15's own page - it
  gets its own section and its own explicit scope decision, never a silent extension of
  `RecommendationPanel`'s existing, deliberately narrow, read-only contract.
