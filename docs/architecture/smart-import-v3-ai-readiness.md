# Smart Import V3 - AI readiness and privacy (Gate 1)

Status: **readiness only.** No live provider, no key, no network call. `IMPORT_UNDERSTANDING_PROVIDER` stays
`unconfigured`. This gate answers one question: *can a model be switched on later without giving up privacy, safety,
determinism, fallback, cost control or auditability?* Measured against a stand-in, never a real model.

Baseline: `main` 1479a8d (after Hardening 1/2 and Question Reduction 1). The benchmark is a reproducible runner,
`python -m tests.benchmarks.smart_import_v3.ai_readiness` (from `services/api`), which writes
`tests/benchmarks/results/smart-import-v3-ai-readiness-v1.json` and `docs/benchmarks/smart-import-v3-ai-readiness.md`. **Its
scope is the FIRST SCREEN** (one understanding per document, scored without the conversation rounds): its P0/P1 are not
comparable with the official full-flow benchmark, only each mode with the same run with no model.

## The principle

```
DOCUMENT
   |  deterministic parser
   |  deterministic structure / domain / semantic inference
   v
ambiguity left?
   |-- NO  --> deterministic import (the model is never asked, never sees the file)
   '-- YES --> egress gate --> ONE call --> deterministic validation --> import / ask / reject
```

**The engine calculates. The model interprets only ambiguity.** It may *propose*: the kind of data, the meaning of a
column, a likely answer to a question NINFA is going to ask. It may not: import, change a row, invent or complete a
value (a check-in, a revenue, an invoice number, hours, a date the file does not hold), change business data, skip a
validation, or decide `READY` alone. The answer schema is closed (a kind, a field per column index with `LOW`/`MEDIUM`,
a choice among the offered questions) - it has no place to put a text, a number or a date.

## What may leave the server (the egress contract)

One JSON document per file, built from the deterministic reading (`understanding_ai.build_evidence`) and then **rebuilt
from scratch by the gate** (`ai/import_understanding/egress.py`). Exact schema:

| Field | Content | Never |
|---|---|---|
| `expected_domain`, `allowed.domains`, `allowed.fields` | NINFA's own vocabulary (static) | - |
| `sheets[]` `{name, role, rows}` | the sheet name reduced to words NINFA's vocabulary knows, its role, its row count | a hotel's or a person's name |
| `title` | reduced the same way | free text |
| `columns[]` `{index, header, kind, values, distinct, pii, samples, range, assigned}` | a **safe label** (short, no personal-data shape, not the name of a person); `TEXT\|NUMBER\|DATE\|MIXED\|EMPTY`; counts; the **class** of personal data (`PII_*`) and *nothing else* for such a column; up to 6 cleaned example words of a column that repeats a few of them; the range of a column of small numbers (at most 7 digits); the field the rules already gave it | a cell of a personal-data column; a value of a free-text column; a whole row; a number long enough to be a telephone number |
| `questions[]` `{id, kind, column, choices}` | only questions whose choices are NINFA's own words (kind of data, meaning of a column, planned or actual hours), with an **opaque id** (`Q1`, `Q2`...) and the index of the column they concern - NINFA's own ids hold the header (`MEANING:<header>`), which is file text; a table question (its choices are sheet names) is never offered, nor one about a column the model is not shown | the header or a sheet name |

Never in it, whatever the path: name, surname, guest, e-mail, telephone, tax code, IBAN, the **file name**, notes,
anything personal found in a header, a sheet name, a title or an example. The instructions are static and trusted; the
evidence is data in its own block.

### The gate (mandatory, in the resolver - not in the provider)

1. **`prepare`** - every free text is read again the way a person reads it (invisible characters removed, look-alike
   letters made Latin, spaces unified), personal-data shapes are replaced, the personal values *of this file* are
   replaced (the same `PersonalDataGuard` that protects the browser), and only then is the text cut short. A header that
   is the name of a person (a staff grid has a column per employee) is removed unless it is made of words NINFA knows.
   Unaccounted-for fields are dropped; an unknown personal-data class is treated as the worst one.
2. **`fit_budget`** - hard limit **6 000 characters** of serialised evidence (the corpus averages 1.8k, max 3.4k). Over it,
   the evidence is reduced deterministically - columns already placed lose their detail, then ranges, then examples, then
   sheets, then columns from the right - and *never* grows. If even the minimum does not fit, **no call**.
3. **`verify`** - the final document, exactly as it would be sent, is decoded and read once more **one string at a time**
   (keys and values, at any depth; never joined): any personal-data shape, or any personal value of the file, in any single
   string and the call is not made (`ResolutionReason.BLOCKED`, codes only in the log). Reading the JSON as one text made two
   innocent neighbours (`@cmd`, `fdp.exe` in a column of hostile cells) look like an address and blocked a call for no reason
   (PB-2). Text that is not JSON is read whole (fail closed).

A provider is handed text that has been through all three. It is never asked to protect anything, and the test doubles
**audit** every request they receive (`tests/import_ai_support.audit`).

## Personal data stays personal, however it is typed

`document_understanding/pii_text.py` is the one place that undoes disguise, for privacy decisions only (the generic
semantic matching is untouched):

* a header is read **every way a person could have meant it** - invisible characters removed *or* taken for a space,
  camelCase split, a glued run of letters split into words only when every piece is a personal-data word - and the
  readings are kept apart (a wrong reading invents words; it must never contaminate the right one);
* a value is looked for in the normalised reading (zero-width space/joiner/non-joiner, BOM, soft hyphen, control
  character, no-break space, full-width `＠`, Cyrillic or Greek look-alikes *inside a Latin word*) and **masked in the
  original text** through a character map, so an address with a zero-width space in the middle is found and masked whole;
* the hourly-rate lock (salary data) uses the same readings.

Before/after on `main`: 111 of 191 disguised personal-data headers were no longer classified; 19 of 29 disguised values
reached the browser and 14 of 29 the model; guest surnames behind a glued or zero-width header reached both; a person's
name used as a column header and a telephone number stored as a number reached the model. After: 0 of each.

## What the model cannot do to the safety level

* A suggestion is **`MEDIUM` at most** (`HIGH` is a structural breach: the answer is invalid). Nothing it says can make a
  file `READY` that was not ready without it, and nothing can make a column certain: only the rules plus the values, or
  the person, can. This is stricter than "needs sufficient validation": validation filters, the person confirms.
* **A column that is part of an ambiguity is not decided by a model**: hours that do not say planned or actual, an amount
  that does not say net or gross, look-alike columns for one field. A field that another column is still a candidate for
  is not given away.
* **The document beats the model.** If the rules say the file is another kind of data than the card, they ask the person
  and the model is **not asked at all**. A suggestion the values of the column contradict is dropped. A personal-data
  column or one the rules placed is off limits (the whole answer is invalid).
* **The model agrees with the card**: no redundant `DOMAIN` question, no confidence added, no `READY`.
  **It disagrees**: none of its column mappings is applied; it can only add a `DOMAIN` question, as a suggestion, when the
  rules saw nothing at all.
* **Prompt injection** in a cell changes nothing: the evidence is data, the answer is a closed choice.

## Cost and calls

At most **two** calls per file (`MAX_CALLS`), usually **one**; a second only after an answer that broke the structural
rules and only if the first took less than 15 s. Never per row, never per column: a 3-row and a 400-row file produce the
same payload. The model is asked only about a file with something open (12.5% of the corpus). Bounds: adapter timeout 20 s,
no retries, `max_tokens` 1 500; an answer over 8 000 characters is ignored unread. Each resolution logs one audit line of
counts and words (reason, calls, payload/response characters, approximate tokens, reduced, redactions, suggestions, prompt
version) - never content.

## When the provider fails

Timeout, 429, 500, 529, connection error, quota exhausted, refusal, an answer that is not JSON or is cut short, an empty or
huge or malformed answer, a raw exception from an adapter that should not raise: the result is **exactly** the one with no
model (verified on the whole corpus, screen by screen), HTTP 200, nothing of the vendor in the response or the log. A file
the engine can import is imported. One call is spent, not two (a transport failure is not retried).

## The port

`ImportUnderstandingProvider` (one method, `suggest(request) -> object`). The business logic - the resolver, the gate, the
validator, the evidence builder and everything that reads a file - imports no vendor SDK and no network library (checked by
parsing the source: `tests/test_ai_boundary.py`); the only file allowed to import `anthropic` is the adapter. With
`unconfigured` the factory builds a resolver with **no provider inside**: it prepares nothing, reads nothing, sends nothing
(a test refuses every socket call across a whole understanding of staff and booking files).

## Before a real provider is switched on (not done here)

1. Run `tests/eval_import_understanding.py` against the chosen model on the synthetic corpus and read precision/recall.
2. Agree the data-processing terms and retention with the vendor; the evidence contains hotel structure (headers, example
   words) even though it contains no person.
3. Decide per-tenant opt-in and a monthly call/token budget with an alarm (the audit line already carries the counts).
4. UI wording for a `MEDIUM` suggestion that guards against automation bias: the benchmark shows what a plausible wrong
   suggestion looks like when a person confirms it blindly.
5. A real-model smoke with canary values (fake PII) in a staging file, confirming the provider logs hold nothing.

## Confirmation is enforced by the server (PB-3)

A suggestion - a model's or a rule's - that is `MEDIUM` with a question open is not a decision. Found by the benchmark: the
proposal of such a file could be posted again to `/imports/mapped` and imported without anybody answering (the dry run said
`can_import: true`); only the page prevented it. It is a workflow-integrity problem, not an authentication one: the backend
is the source of truth on `ASK` / `READY`.

**Protocol.** The decision (`proposal`) NINFA issues carries `smart_import`: the answers the understanding was made with. Before
a decision that carries it is judged (`/import-validation`) or imported (`/imports/mapped`), the server reads the file again
with exactly those answers - **without any model** - and accepts it only if that reading is `READY` (no question, no
blocker) and gives exactly this mapping; the mapping used is then the server's own. Otherwise it answers `409`:
`UNRESOLVED_IMPORT_QUESTIONS` (with the open question ids and blockers) or `IMPORT_DECISION_CHANGED`. Nothing is written.

**Why the client cannot fake it.** There is nothing to fake: the reference is not a claim of the client ("confirmed") but the
name of the reading to verify, and the verdict is the server's own recomputation, which depends only on the file and on the
answers - answers the server validates (an unknown answer is a `422`). The only way from `ASK` to `READY` is to answer the
questions through the understanding, and an answer is a specific choice (`column_fields: {Total: room_revenue}`), not a flag.
No secret, no signature, no stored state, no migration.

**One semantics for everything.** A model's suggestion and a rule's (`CONFIRM:Total`) are the same thing here: a question
open is a question open, and so is a `TABLE`, `DOMAIN`, `PERIOD`... A model cannot make a file ready (it is capped at
MEDIUM and the verification does not use it); a person can choose a different column than the suggested one.

**Manual matching (Smart Import V2).** A matching the person builds by hand carries no reference and is judged on its merits
as it always was: the page drops the reference when the person takes over ("Abbina le colonne"). The contract of that
endpoint remains "the person's own matching".

## Known limitations (found while building this)

* **A client can still import by declaring a matching to be the person's own** (omitting the reference): that is the manual
  contract, not a Smart Import decision. What is closed is the posting again of NINFA's own decision, accidentally or
  by copying the suggestion.

* **`fit_identifier` cannot tell an identifier from any column of distinct values.** A wrong model that names an amount
  column or a "KPI" column as the reservation code passes the value check and stays as a MEDIUM suggestion with an open
  question (BO05, BO08). The date fields have the same limit between two date columns ("Ultima modifica" for the work date,
  L12). Nothing deterministic separates them; the person's confirmation is the protection.
* **Size alone demotes a sheet to "summary"** (below 25% of the best table) in `document.py`; the coverage rule of PB-1 treats
  such a sheet as data when it fits the kind chosen and has records, but the role label itself is still size-based.
* The quality of a real model is unmeasured: everything here uses stand-ins.
