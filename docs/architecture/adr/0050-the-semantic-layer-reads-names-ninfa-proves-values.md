# ADR 0050: The semantic layer reads names; NINFA proves values

Status: accepted (Smart Import OpenAI Intelligence V1). One new runtime dependency (`openai`), no migration, no change to any analysis, detector, Expected value, Decision, Mia, the
scheduler, the Windows runtime supervision or the UI. Builds on [smart-import-v3-ai-readiness](../smart-import-v3-ai-readiness.md) (the AI port, the egress gate and the closed
validator) and on [import-scope-semantics-v1](../import-scope-semantics-v1.md) (FULL / PARTIAL / DELTA), none of which it changes.

## Context

Smart Import V3 already had an AI port: a provider that is handed a cleaned description of the shape of a file, never the file, and answers in a closed shape; a gate that cleans and
verifies what leaves; a validator that never trusts what comes back; a deterministic fallback for every failure. It was built and measured against stand-ins, never run on a real model,
and one rule was fixed on purpose: **a model's suggestion is MEDIUM at most, a person confirms it, and the server verifies every decision by reading the file again WITHOUT any model**
(PB-3). That rule keeps a model from ever deciding. It also means a model can never remove a question: the best it can do is to pre-fill the answer to a question the person still has to
answer.

The brief for this gate is a measurably smarter Smart Import "without lowering safety": more files read correctly, with fewer questions. Both cannot hold unless there is a narrow, honest
way for a model's reading to end in a column NINFA treats as certain.

## What the gate found, by measuring the files, before deciding

* With a status or channel header the rules do not know ("Condizione", "Distribuzione") the rules do not ask a question: they send the person to the manual matching screen
  (`MISSING_REQUIRED`). This is the cost a reader of words can take away.
* With the department column called "Postazione" the rules place it by its values, are not sure, and ask one `CONFIRM` question. A reader of the name removes it.
* With ONE of the hours columns read ("Ore previste") and the other called something the rules do not know ("Impegno reale", "Time worked"), the rules call the file READY and the
  column is silently left out. This is a false automation of the rules alone (the benchmark counts it as P0). A reader that notices the unread column turns it into a question.

## Decision

1. **A second adapter on the existing port, not a second system.** `OpenAIImportUnderstandingProvider` implements `ImportUnderstandingProvider`. The egress gate, the personal-data scrub,
   the validator, the two-call limit, the fallback and `UnderstandingService` are reused as they are. It is the only file that imports `openai`; the boundary test says so for both vendors.
2. **Responses API, Structured Outputs, `store=false`.** `responses.create` with a strict JSON schema generated from a Pydantic contract (the SDK's public `pydantic_function_tool`), the
   answer validated by the same Pydantic model. (`responses.parse` does the same but raises before the status, the refusal and the usage of a bad answer can be read, and the audit and the
   fallback need them.) `reasoning.effort` is `medium`; the one second call the resolver may make after an answer that broke the shape uses `high`. No tool, no web search, no conversation
   state, no `user` or `safety_identifier`. The SDK's own retries are off: the adapter repeats a request at most once after a transient failure (429, 5xx, dropped connection), never after a
   timeout, a refusal or an exhausted quota, inside a total time budget; every failure is ONE stable word (`FailureKind`) and the vendor's message, which can hold a key, is never kept.
   Model default `gpt-6.1-sol`, configurable; the model name is NOT verified against the vendor here (no key).
3. **A closed contract with room for "I do not know".** `semantic-v1`: a status (`INTERPRETED`, `PARTIAL`, `AMBIGUOUS`, `INCOMPATIBLE`, `INSUFFICIENT_DATA`), a kind of data or `UNKNOWN`, a
   claim (`LOW` or `MEDIUM`; there is no `HIGH`), the header's plausibility, a reading per column with a field of the kinds NINFA really has (built from its registries, enumerated in the
   schema) or `NONE` and a **reason code** instead of free text, the columns it cannot place, the ambiguities it sees, the answers to the questions NINFA offered, closed warnings, and
   whether a person should still be asked. There is no field for a number, a date, a name or a sentence: no value of the file can come back and nothing a cell says can be echoed. A model
   is never made to choose. Format interpretation (date order, decimal mark) is NOT in the contract: the evidence shows no values from which to read it, and those questions stay the
   person's.
4. **Three modes, one switch.** `SMART_IMPORT_AI_MODE`: `off` (default; builds a resolver with nothing in it, loads no SDK), `shadow` (the model is asked and MEASURED; the answer returned
   is the rules' own; what ASSIST would have done is recorded by replaying the SAME reading through the real code, so the comparison is exact and cannot drift) and `assist`. A mode other
   than `off` with no key is not an error: Smart Import runs as `off` and says so once.
5. **ASSIST: suggestions, and one narrow certainty.** The model's reading is applied as before - a MEDIUM suggestion with a question for the person - and a column becomes certain only
   through `corroborate`: the NAME is read by the model, the VALUES are proved by NINFA. The field must be one whose values NINFA reads from a closed vocabulary (booking status, channel,
   department, cost category) and not money; the column must hold enough values; NINFA must know every word in it (its own, or what the person taught) or its vocabulary must recognise
   most of them; the model's whole reading must be clear (status `INTERPRETED`, overall `MEDIUM`, no ambiguity, no question left for a person, a plausible header, no sentence of orders
   noticed); and no other free column may hold the same kind of words. **Dates, hours, amounts, counts and identifiers are never promoted**: their values cannot tell one such column from
   another, so the person still confirms them. **Money is never placed by a model at all.** A column a person confirmed is never changed: a different reading is counted as a conflict, and as
   a source-learning conflict when the person confirmed it. A column the rules placed without being sure is confirmed in the same way when the model reads the same name.
6. **A certain column is a recorded answer the server reads again with no model.** PB-3 stays exact: the server still verifies a decision by reading the file again without any model. The
   promotion is therefore recorded in the decision as `assisted_fields` (`{"Condizione": "status"}`, in the answers the understanding was made with); the server applies the same names, at
   MEDIUM, and the same chain (the words NINFA knows, the vocabulary, one candidate only) decides again whether they are certain, from the file alone. It is checked against the file every
   time and is not a confirmation by a person (it teaches nothing to Source Learning). A client that forges it gains what the values prove and nothing else - what a person could say with
   `column_fields`, with more checks.
7. **The layer may also ask when something might be silently left out.** A requirement met by ONE of its alternatives (planned OR actual hours) while a column nobody read is still there is
   worth a call: the answer becomes a question, not a file that looks complete.
8. **Source Learning outranks the model.** The order is: NINFA's hard rules; what a person confirmed (this answer, or what this source remembers); the rules' reading; the model's reading;
   a question. A model that disagrees with a column that is already placed is counted, never applied.
9. **Observability without content.** One audit record per use: mode, provider, model, prompt and schema version, outcome and fallback reason, calls, retries, latency, tokens, request ids,
   columns by certainty before and after, the verdict and the number of questions the person is shown with and without the model, suggestions, promotions, agreements and conflicts. Words,
   counts and ids only; the model's reasoning is neither asked for nor kept; the vendor's logger stays at WARNING so the SDK never writes the cleaned evidence at DEBUG.
10. **Endpoint.** `OPENAI_BASE_URL` (a custom https endpoint) or `OPENAI_DATA_RESIDENCY` (`eu`, `us`...: the SDK's own regional endpoints), never both; nothing is hard-coded. The EU endpoint
    is documented, not assumed: it applies only when the OpenAI project is set up for it.

## What this gate did NOT do, on purpose

* No fine-tuning. The "training" is a benchmark and its fixtures (`openai_intelligence`), reused from the official corpus: no second benchmark infrastructure.
* No change to FULL / PARTIAL / DELTA: the model is told in so many words that it neither decides nor hints at whether a file replaces, completes or amends what NINFA holds, and the
  existing suites of those rules run again, unchanged, with the layer on.
* No change to how a file's header row or table is chosen: the model may say that the row taken as the header looks like values, and then nothing is promoted; it cannot choose another row
  (rows of the file never leave NINFA).
* No UI change: the existing wording ("suggerito da NINFA, da controllare") names no vendor.

## What is NOT known

The real quality of any model on these files. Everything measured here uses stand-ins and says what NINFA does with a reading that is right, partly right, confidently wrong or hostile.
`LIVE OPENAI ACCEPTANCE: NOT RUN - OPENAI_API_KEY NOT CONFIGURED`; `tests/live_openai_acceptance.py` is the script that runs it, and it never reports a pass it did not earn.
