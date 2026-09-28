# Ask NINFA Language Hardening V1 (`ask-ninfa-language-v1`, Gate 19.1)

Gate 18 built Ask NINFA's grounded, whitelisted architecture; Gate 19 wired in a real provider. The
first live answer both produced showed the architecture was sound but the LANGUAGE was not: raw
engine identifiers (`forecast_rooms`, `REV_OCCUPANCY_RISK`, `TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL`,
`REVIEW_DEMAND_POSITIONING`, ...) reached the user's own answer text. This gate closes that gap
structurally - "whitelisted" now also means "human-presentable" - without touching Expected, any
detector, Priority, the Decision Layer, the Recommendation Engine, thresholds, formulas, confidence,
or ranking. See ADR 0026 for the "why" behind every choice below; this document is the "what".

## User-language boundary

Ask NINFA's context boundary now has two layers, not one:

1. **Structural (primary)**: the model-facing `AskDecisionContext` never CONTAINS a raw engine
   identifier - `semantic_labels.py` translates every one of them to Italian before the context is
   even built. There is nothing to leak because the source string is not there.
2. **Prompt-level (secondary)**: the system instructions (`instructions.py`, version
   `ask-ninfa-v1.1`) additionally tell the model never to use technical field names, enum codes, or
   snake_case even if it somehow encountered one, and to keep answers short and focused.
3. **Output validation (tertiary, fail-closed)**: `technical_leak.py` checks the model's own free
   text for a leak anyway, as defense in depth, and fails the whole answer closed if it ever fires.

## Semantic model-facing context

`app/modules/ai/ask_ninfa/semantic_labels.py` is the ONE place every raw engine identifier this
codebase can produce is translated to Italian:

| Raw | Now |
| --- | --- |
| `decision_type` (`PriorityDecisionType`) | `decision_label` - Italian title (`decisionTypeTitles`' own wording) |
| `Decision.status` (`OPEN`/`RESOLVED`) | `decision_status` - "Aperta"/"Risolta" |
| `source_status`/`lifecycle_transition` | one `status_label` - "Rilevata"/"Ancora presente"/"Risolta"/"Ricomparsa"/... (`lifecycleEventCopy`'s own wording) |
| `ActionCode`/`category` | `title`/`description` - Gate 17's own recommendation copy |
| `RiskNote` | a mapped Italian sentence |
| `cost_category`/`labor_category` | a mapped Italian category name |
| every whitelisted fact/evidence key | an `AskDataPoint {label, value, unit}` |

`AskDataPoint` (`app/modules/ai/ask_ninfa/types.py`) is the new model-facing fact/evidence shape:

    AskDataPoint(label="Previsione camere", value="28", unit="camere")

`value` is copied verbatim from the whitelisted `facts_payload`/`evidence_payload` string/number -
never reformatted, rounded, or recomputed, only relabeled. `facts`/`evidence` on
`AskObservationContext` are now `tuple[AskDataPoint, ...]`, never a `dict[str, value]` keyed by the
raw internal name - there is no raw key anywhere in the shape, not even as a JSON object key.

A raw fact/evidence key with no entry in `semantic_labels.py`'s mapping tables is DROPPED, never
passed through raw - almost always because it is an internal detector CONDITION flag
(`percent_condition`, `gap_condition`, an upper-fence threshold) the surrounding numeric facts
already make redundant to spell out, or a pure technical/versioning value (`rules_version`) with no
explanatory content for a user.

## Internal-code exclusion

Removed from the model-facing context entirely (never mapped, because nothing in it stands in for
them - see ADR 0026, "why raw reason codes are omitted"):

- `reason_codes` - the numeric facts already represent the same phenomenon a reason code would name.
- `priority_rank` - a V1 product preference: never verbalise a bare numeric rank to a user. If a
  future gate needs to convey relative priority, that is a NEW, deliberate decision (e.g. a
  boolean-ish "among the higher-priority decisions"), not a resurrection of the raw integer.
- `RecommendationContext.status` / `requires_human_review` - the raw
  `AVAILABLE`/`NOT_AVAILABLE`/`INSUFFICIENT_CONTEXT` enum and the always-`true` boolean are both
  redundant with `primary_action` being `None` or not, and with the system instructions' own
  unconditional "never propose an autonomous action" rule.
- `ActionCategory`/`ActionScope` - the mapped `title`/`description` already convey what kind of
  review matters; the category/scope codes added nothing a user needs.

## Recommendation mapping

`primary_action_title_of`/`primary_action_description_of`/`supporting_action_title_of`
(`semantic_labels.py`) reuse the EXACT Italian wording `apps/web/lib/recommendations/copy.ts`
already ships for the same `ActionCode` - one vocabulary, never a second translation that could
drift from the Recommendation UI. `ActionCode` stays the real engine's own source of truth; nothing
here infers a recommendation from `decision_type` (see ADR 0023's own "why copy maps ActionCode,
never DecisionType", which this gate's mapping equally respects). A supporting check gets only a
`title` (`description: None`) - the real UI gives supporting checks a single short label too, never
a second invented sentence.

## Reason-code handling

See "Internal-code exclusion" above - omitted, not mapped. No per-reason-code Italian translation
table exists; the ~60 reason codes across four detector modules stay entirely internal.

## Number selection

The system instructions (rule 16) tell the model to use only the numbers actually needed to answer
the question - typically 2-4 - never to enumerate every fact in the context. This is a prompt-level
rule, not a structural limit: the context itself still carries every semantically-labeled fact the
detector produced, so the model has what it needs regardless of which 2-4 numbers a specific
question calls for.

## Answer brevity

`MAX_ANSWER_CHARS` (`app/modules/ai/ask_ninfa/types.py`) is now **700**, down from 1200 - chosen
from the 650-800 range, matched to "2-3 short Italian paragraphs" (system instructions rule 18) and
roughly half the character footprint of the live answer that exposed this gate (472 output tokens).
No token estimator was added to the business layer - this stays a plain post-hoc truncation
character count, exactly the mechanism Gate 18 already established (`answer_validation.py`'s
`_truncated`), just with a smaller ceiling. The primary brevity lever is the strengthened system
instructions (rules 13-20 below), never truncation - truncation remains the honest backstop for an
answer that ran a LITTLE long, not the mechanism relied on to make answers short in general.

## System instructions (`ask-ninfa-v1.1`)

Eight new explicit rules (13-20), on top of Gate 18's original twelve, unchanged:

13. Never mention technical field/class/module names.
14. Never mention enum values or technical codes.
15. Never use snake_case or `_exact`/`_pp_exact`-style suffixes.
16. Use only the numbers actually needed (typically 2-4) - never dump the whole context.
17. Answer the question first, never just summarise everything known about the decision.
18. Maximum 2-3 short paragraphs.
19. Professional, concrete, natural tone - never a technical manual or a log line.
20. An economic-proxy figure always carries its "estimate, not certain" caveat (reinforces rule 7).

Rule 5 (priority) was reworded: "non ricalcolare la priorità" (which assumed a rank might be
present) is now "non menzionare un rango... il context non te la fornisce apposta" - honest about
the fact that `priority_rank` no longer reaches the context at all.

## Technical-leak validator

`app/modules/ai/ask_ninfa/technical_leak.py`'s `contains_technical_leak(text)` checks a candidate
answer/limitation for:

- an exact, whole-word match against a CLOSED set built from the real, installed enums/whitelists
  this codebase already has (`PriorityDecisionType`, `DecisionStatus`, `LifecycleTransition`,
  `EvaluationStatus`, `ActionCode`, `ActionCategory`, `ActionScope`, `RiskNote`,
  `RecommendationStatus`, `CostCategory`, `LaborCategory`, all four detector modules'
  `ReasonCode`s, and every key in `FACTS_WHITELIST`/`EVIDENCE_WHITELIST`) - constructed from the
  real Python objects at import time, never re-typed by hand, so it cannot silently drift from the
  vocabulary it is meant to catch;
- any snake_case-shaped token at all (`\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b`) - Italian prose
  never naturally joins words with an underscore, so this is a safe, narrow signal even for an
  identifier not in the closed list (e.g. a future sixth decision type).

Wired into `answer_validation.validate_model_answer`: a leak in the answer OR any limitation fails
the WHOLE response closed.

## Fail-closed behaviour

A detected leak returns `None` from `validate_model_answer` - the EXACT same mechanism already used
for an empty or malformed answer. `AskNinfaService` already treats `None` as `AskStatus.UNAVAILABLE`
with `answer: null`; no new status value was added, no new branch in the service. A `WARNING`-level
log line records only `technical_leak_detected=true` - never the leaked text itself, matching this
codebase's existing "safe metadata only" logging discipline (Gate 19's own Anthropic adapter
logging). No post-hoc rewrite, no second provider call - see ADR 0026, points 6 and 8.

## UTF-8 finding

The first live smoke test's terminal output showed `perchÃ©`/`prioritÃ `/`Ã¨` - classic mojibake from
UTF-8 bytes decoded as Latin-1/CP-1252. `test_utf8_accented_italian_characters_survive_the_real_
http_json_roundtrip` (`test_ask_ninfa_api.py`) sends real accented Italian text through the actual
FastAPI JSON response path with a real HTTP test client and asserts it returns byte-for-byte
identical. It does - this was the local PowerShell/terminal display, never the backend's own
encoding, and no product encoding change was made (see ADR 0026, point 12).

## Live acceptance criteria

After this gate's review, the SAME real decision (`REV_OCCUPANCY_RISK`,
`8e2aafab-03ff-4d0c-83d9-da9dc6fea9ba`) will be asked the same question
("Perché NINFA mi sta mostrando questa decisione?") again, manually, comparing:

- token counts and latency (input/output tokens, elapsed ms) against the BEFORE baseline (3071
  input / 472 output / 7566 ms / ~$0.010862);
- answer quality: no raw engine identifier, ≤3 short paragraphs, answers the question first, states
  the economic-proxy caveat if a proxy figure is cited, preserves human-review framing.

This gate does not execute that live call - it is explicitly deferred to manual review.

## Update (Gate 19.1b): first live acceptance result and further polish

The live acceptance call above ran: `3772` input / `375` output / `6165` ms. Technical leakage was
gone, grounding stayed correct, and the real provider worked - but the answer was still judged too
technical/dense (still used "confidence", "pattern storico", "atteso a fine finestra"; cited
affidabilità and 12 historical comparables even for a generic "perché" question; showed 10 numbers
at once). It also ended mid-word ("...impatto sui ricavi di 6…") - see "Truncation, fail-closed"
below.

**Language polish (instructions rules 21-25, `ask-ninfa-v1.2`):** answer-first opening (never
"NINFA ha rilevato..."/"Secondo i dati..."); question-sensitive number/data selection (a generic
"perché" question: 3-4 numbers max, booked/available → scostamento → gap%, no
affidabilità/comparable-count/economic-proxy unless the question asks for it); one final natural
recommendation sentence, human review implied ("la decisione finale resta a te") rather than
declared; a 300-500 character STYLE target, explicitly separate from the 700-character hard
ceiling; "affidabilità" preferred over "confidence" (also renamed at the JSON-key level, see
"Confidence" in ask-ninfa-v1.md), "andamento storico" over "pattern storico", "livello atteso" over
"atteso a fine finestra" (both `semantic_labels.py` label text, renamed).

**Truncation, fail-closed (ADR 0026's own update, points 13-14):** the trailing "…" was traced,
statically, to `_truncated()`'s character-count slice landing mid-digit of "600" - not a model
artefact, not a PowerShell display issue. `MAX_ANSWER_CHARS` (700) is unchanged and remains the
hard validation ceiling; an answer over it now fails closed to `UNAVAILABLE` instead of being
silently cut.

**Context size:** input tokens grew 3071 → 3772 across Gate 19.1 itself. A full field-by-field
audit (ADR 0026's own update, point 16) found no field clearly duplicated or useless for any
supported question - the growth is verbosity-for-clarity (labels + full sentences replacing raw
keys/codes), the expected cost of this gate's own purpose. Nothing was removed.

## Limitations (intentional, documented debt)

- `semantic_labels.py`'s mapping tables are hand-curated per decision type - a sixth decision type
  needs an explicit new set of entries before it can produce a user-presentable context at all.
- The 700-character/2-3-paragraph brevity target is a V1 product judgment call, not measured against
  real usage data yet.
- The technical-leak validator's snake_case regex is a safety NET, not a substitute for
  `semantic_labels.py`'s own structural exclusion - a provider that started returning verbose,
  jargon-laden but non-snake_case prose (e.g. spelling out "REV OCCUPANCY RISK" with spaces) would
  not be caught by this validator; the primary defense remains that the context never contains the
  identifier to begin with.
