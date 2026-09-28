# 0026 — Ask NINFA language hardening V1: internal codes stay internal

## Context

The first real Anthropic-backed live smoke test (Gate 19) answered `status=ANSWERED` correctly, but
its Italian prose exposed the engine's own internal vocabulary verbatim - `forecast_rooms`,
`occupancy_gap_pp_exact`, `reason_codes`, `TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL`,
`REVIEW_AVAILABILITY`, `REVIEW_DEMAND_POSITIONING`. The context Gate 18/19 built was already
correctly WHITELISTED (never a raw ORM row, never PII) - but "whitelisted" and "human-presentable"
are different bars, and this gate's own review found the context had only ever cleared the first
one. This is a presentation/language-quality problem, never a business-logic one: Expected, the
five detectors, Priority, the Decision Layer, the Recommendation Engine, thresholds, formulas,
confidence and ranking are all untouched by this gate.

## Decision

1. **Why raw engine identifiers never reach user prose.** A user is a hospitality operator, not a
   developer of this codebase - `REV_OCCUPANCY_RISK`/`forecast_rooms`/`TRIGGER_...` mean nothing to
   them and actively damage trust in a system whose whole premise is "explains, in Italian, what
   matters and why". The fix has to remove the SOURCE of the leak, not police its symptoms.

2. **Why prompt-only protection is insufficient.** Gate 18's system instructions already told the
   model "answer only from the context" and "respond briefly" - and the model still echoed
   `forecast_rooms` back, because that string was LITERALLY present in the context it was told to
   answer from. A system prompt is a request the model can misjudge, be attacked around, or simply
   fail to satisfy under load; the context Gate 19.1 now builds physically does not CONTAIN the
   identifier to leak, which is a strictly stronger guarantee than asking nicely not to repeat it.

3. **Why model context is semantic.** `semantic_labels.py` translates every raw engine identifier
   this codebase can produce - `decision_type`, `DecisionStatus`, `source_status`/
   `lifecycle_transition`, `ActionCode`/`category`, `RiskNote`, `cost_category`/`labor_category`,
   and every whitelisted fact/evidence key - into Italian BEFORE it reaches `AskDecisionContext`.
   Facts/evidence are no longer a `dict[str, ContextValue]` keyed by the raw internal name; they are
   a `tuple[AskDataPoint, ...]`, each one `{label, value, unit}` - there is no raw key anywhere in
   the shape for the model to echo, not even as a JSON object key. Wherever the real product UI
   already ships an Italian phrase for the same concept (Gate 15's `decision-card.tsx`, Gate 17's
   recommendation copy, `apps/web/lib/copy.ts`), this module reuses the EXACT same wording, so a
   user reads one consistent vocabulary across the UI and Ask NINFA, never two different
   translations of the same fact.

4. **Why raw reason codes are omitted, never mapped.** Reason codes (`TRIGGER_...`/`CLEAR_...`/...)
   are machine-level detector vocabulary explaining WHY the numeric rule fired - and the numeric
   facts already surrounding them (the gap, the shortfall, the delta) already represent that same
   phenomenon in a form a user can read directly. Mapping ~60 reason codes across four detector
   modules to Italian sentences would duplicate information already present in the facts, with a
   real risk of the two disagreeing over time; omitting them entirely is simpler, smaller, and
   loses nothing a user needs. `priority_rank` is omitted for the same reason plus an explicit V1
   product preference: never verbalise a bare numeric rank ("rank 1") to a user.

5. **Why recommendation codes are mapped, not omitted.** Unlike reason codes, an `ActionCode` has no
   numeric fact standing in for it - "REVIEW_DEMAND_POSITIONING" is the ONLY signal that a specific,
   meaningful suggestion exists at all, so it cannot simply be dropped. It is mapped instead, reusing
   the SAME Italian title/description the Recommendation UI already ships (Gate 17's
   `recommendation-ui-v1` copy) - one hand-audited vocabulary, never a second translation of the
   same code that could drift from the UI's own.

6. **Why no post-hoc answer rewrite.** A find/replace or regex substitution over a model's own text
   cannot be proven correct for language the closed mapping tables were never audited against - it
   would silently produce a plausible-looking but unverified sentence, which is a worse failure mode
   than an honest `UNAVAILABLE`. This gate never rewrites; `technical_leak.py`'s job is detection,
   never correction.

7. **Why leakage fails closed.** `technical_leak.contains_technical_leak` runs on every candidate
   answer/limitation, inside `answer_validation.validate_model_answer`, using the SAME fail-closed
   mechanism that already exists for a malformed/empty answer: a leak makes `validate_model_answer`
   return `None`, and `AskNinfaService` already treats `None` exactly like a provider exception -
   `AskStatus.UNAVAILABLE`, `answer: null`. No new status value, no special case: leakage is just
   one more reason a candidate answer fails the SAME validation gate everything else goes through.

8. **Why no second provider call.** Asking the model to "try again without the technical terms"
   would double cost and latency for a single-turn, best-effort explanation, and there is no
   guarantee the second attempt is actually cleaner - it is simply a second, equally-unverified
   output. `UNAVAILABLE` is an already-correct, already-tested Gate 18 outcome; reusing it needs no
   new call, no new state, no new failure mode.

9. **Why answers are shorter.** The live answer that exposed this gate ran to 472 OUTPUT tokens of
   dense, technical prose - the opposite of "breve e operativo" Gate 18's own instructions already
   asked for. `MAX_ANSWER_CHARS` drops from 1200 to 700 (`app.modules.ai.ask_ninfa.types`) - not a
   token estimator added to the business layer, just a smaller post-hoc truncation ceiling, backed
   by eight new, explicit system-instruction rules (max 2-3 paragraphs, 2-4 numbers, answer the
   question first, no data dump) that address the ROOT CAUSE (verbose generation), with truncation
   staying what it always was: an honest backstop, never the primary brevity mechanism.

10. **Why numerical facts remain exact.** `AskDataPoint.value` is the SAME string the whitelisted
    `facts_of`/`evidence_of` payload already carried - copied, never reformatted, rounded, or
    recomputed. Gate 19.1 changes WHAT LABEL a number is presented under, never the number itself;
    the "engine calculates, AI explains" principle from Gate 18 (ADR 0024) is unchanged.

11. **Why the economic proxy caveat remains.** `revenue_gap_proxy`/`ota_room_revenue_exposure`/
    `labor_cost_gap_proxy_exact` are now presented under a label that ALREADY states "stima
    indicativa, non un valore certo" - the caveat lives in the label itself, not only in the system
    instructions' own rule (still present, now rule 20 too), so the model cannot cite the figure
    without the caveat traveling with it structurally.

12. **Why the PowerShell mojibake is not a product bug.** The first live smoke test's terminal
    output showed `perchÃ©`/`prioritÃ `/`Ã¨` - classic UTF-8-bytes-decoded-as-Latin-1/CP-1252
    mojibake. This gate added `test_utf8_accented_italian_characters_survive_the_real_http_json_
    roundtrip` (`test_ask_ninfa_api.py`), which sends real accented Italian text through the REAL
    FastAPI JSON response path (`TestClient`, a real HTTP client, not a mock) and asserts it comes
    back byte-for-byte identical. It does. This proves the encoding artefact was the local
    PowerShell/terminal display, never the backend's own JSON encoding - no product encoding change
    was made without this evidence, exactly per this gate's own instruction not to "fix" something
    never shown to be broken.

## Alternatives considered

- **A single blanket regex stripping anything ALL_CAPS or snake_case from the model's raw context
  before serialization**, instead of an explicit per-field mapping table. Rejected: a blind regex
  cannot distinguish a legitimate value that happens to look technical from an actual internal
  identifier, and (per this gate's own explicit instruction) risks either under- or over-blocking in
  ways a hand-audited mapping table does not. `semantic_labels.py` is closed and explicit: a key
  with no entry is DROPPED, never guessed at.
- **Keeping raw `facts`/`evidence` as a `dict[str, value]` and relying only on the leak validator to
  catch the model echoing a key.** Rejected as the PRIMARY defense (the validator still runs, as
  defense in depth): a dict keyed by the raw internal name still shows the model the identifier at
  generation time, which is strictly weaker than a shape that never contains it in the first place.
- **A machine-translated or heuristic label generator** (e.g. `"occupancy_gap_pp_exact"` ->
  "Occupancy Gap Pp Exact" -> Italian via some generic humanizer). Rejected: exactly the
  "plausible-looking but wrong" risk point 6 already rejects for output rewriting, applied to input
  instead - a heuristic humanizer cannot know that `_pp_exact` means "percentage points, decision
  precision" rather than an arbitrary suffix, and would still leak the underlying key shape.

## Consequences

- A sixth decision type, or a new fact/evidence key on an existing one, needs an explicit new entry
  in `semantic_labels.py`'s own mapping tables before it can ever reach a user - an omission fails
  safe (the fact is silently dropped from context), never unsafe (never passed through raw).
- `technical_leak.py`'s closed identifier set is audited against the real enums/whitelists at
  IMPORT time (constructed from `{value.value for value in Enum}`, never re-typed by hand) - a
  future gate adding a new `ActionCode`/`ReasonCode`/category value is automatically covered by the
  validator without an edit to this file, though `semantic_labels.py`'s own mapping tables still
  need an explicit new entry to make that new value ever reach a user-presentable label.
- A future Ask UI can render `AskDataPoint.label`/`value`/`unit` directly as a structured fact list
  if useful, without re-deriving Italian copy - the same wording the model already saw.
- This gate's brevity rules (700 chars, 2-3 paragraphs, 2-4 numbers) are a V1 product judgment call,
  not a mechanically-derived limit - a future gate may revisit them with real usage data.

## Update (Gate 19.1b) — the first technical-leak-free live answer was still too dense

Live acceptance of the gate above confirmed leakage was solved, grounding stayed correct, and the
real provider worked - but the answer was still judged too technical/dense, and its own trailing
"…" turned out to mark a real, unrelated defect. Four further, narrowly-scoped changes:

13. **Why an overlong answer now fails closed instead of being truncated (reverses ADR 0024's own
    "truncate, never reject" decision).** The live answer ended "...impatto sui ricavi di 6…" - the
    real figure was 600, cut mid-digit by `_truncated()`'s raw character-count slice
    (`answer[:MAX_ANSWER_CHARS]`), which has no concept of a word or number boundary. On a product
    whose entire premise is "never show a wrong number", a silently truncated one that now READS
    AS a different, smaller, wrong number is strictly worse than an honest `UNAVAILABLE` - ADR
    0024's original reasoning ("a real answer that ran a little long is more useful truncated than
    discarded") assumed truncation could only ever cut PROSE, never silently corrupt a fact.
    `MAX_ANSWER_CHARS` (700) stays exactly where it was - a hard VALIDATION ceiling, never lowered -
    only its enforcement changed from slice-and-append to fail-closed.
14. **Why the style target (300-500 characters) is a SEPARATE, softer number from the hard
    ceiling (700).** Conflating "how long an answer should aim to be" with "the absolute maximum
    the system will accept" was itself part of why answers ran long - a model given only a hard
    ceiling has no signal to aim shorter than it. The style target lives in
    `instructions.py`'s own prompt-level guidance (rule 24) only; `MAX_ANSWER_CHARS` never changed.
15. **Why "confidence" was replaced with "affidabilità" structurally, not only in prose
    instructions.** The live answer said "la confidence del rilevamento è 100" - traced to TWO
    sources at once: `instructions.py`'s own rule 4 used the English word "confidence" as if it
    were correct terminology (teaching the model to reuse it), AND the serialized JSON key itself
    was literally `"confidence"`. Both were fixed together (rule 4 now says "affidabilità", never
    "confidence"; the JSON key is now `"affidabilita"`) - the same "structural over prompt-only"
    reasoning as point 2 above, applied to a single word instead of a whole identifier class.
16. **Why no context field was removed for token economy.** Input tokens grew 3071 → 3772 across
    Gate 19.1 - a full audit of every context field (this update) found NONE clearly duplicated or
    useless for every supported question: `forecast_rooms`/`expected_final_rooms` are two genuinely
    different detector-computed numbers (not the same fact twice); `evidence`'s confidence-adjacent
    fields (`baseline_confidence`/`pattern_confidence`/`pattern_pair_count`) matter specifically for
    a reliability question, which a generic "perché" question simply chooses not to cite (an
    INSTRUCTION-level selection, rule 22, never a context-level removal); `history`'s own
    last-entry/`latest` duplication is conditional (only when `episode_count == 1`) and already an
    intentional, tested Gate 18 design choice (`test_10_11_history_bounded_and_chronological`). The
    token growth is the expected, accepted cost of Gate 19.1's OWN purpose - semantic labels and
    full recommendation sentences are inherently more verbose than the raw keys/codes they replaced
    - never a sign of duplicated data. Per this gate's own explicit instruction not to optimise
    prematurely or sacrifice grounding for token savings, nothing was removed.

### Alternatives considered (Gate 19.1b)

- **Truncating at a word boundary (`rsplit(" ", 1)`) instead of failing closed.** Rejected: still
  loses the last, possibly load-bearing word/number of a real answer, and still requires deciding
  what counts as an acceptable amount lost - fail-closed needs no such judgment call and matches
  every other validation failure in this same function.
- **Lowering `MAX_ANSWER_CHARS` below 700 to force brevity structurally.** Rejected, per this
  gate's own explicit instruction: the ceiling is a safety backstop, not the brevity mechanism: a
  model that naturally writes 900 characters and gets hard-capped at 500 would fail closed far more
  often than one guided by prompt-level style rules toward 300-500 in the first place.
- **A second pass that rewrites/shortens an accepted answer post-hoc.** Rejected for the same
  reason ADR 0026's original point 6 rejected rewriting a leaking answer: an edited answer is not
  one this codebase's own validation ever actually checked.
