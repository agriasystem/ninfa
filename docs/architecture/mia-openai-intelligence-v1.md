# Mia OpenAI Intelligence V1

Status: implemented on branch `feature/mia-openai-intelligence-v1` (local, not pushed). Decision record:
[ADR 0055](adr/0055-mia-openai-intelligence-v1.md). Migration `0017_mia_conversations`.

> **The engine calculates. Mia understands, links and explains.**

Mia is the assistant of NINFA: the person asks, in their own words, anything about the product, the property, the Decisions, the
metrics, the imports, the sources and the structure, and Mia finds the right facts, links them and answers. She is **read-only**,
**never invents a NINFA figure or feature**, and when she does not know she says what is missing.

## 1. Architecture

```
POST /properties/{id}/mia/messages     (auth -> tenant -> property resolved BEFORE the handler; body is closed)
   |  classify_refusal  (an action / personal data / an injection phrase)  -> REFUSED, never reaches the model
   |  ui_context  -> validated against THIS person's workspace and property and the registry  -> PageContext (a hint)
   |  conversation -> recent messages verbatim + a deterministic summary of the rest
   v
MiaOrchestrator.run                       <= 3 tool rounds, <= 8 calls, <= 1 correction, 90 s, reasoning chosen by policy.py
   |     +--------------- ToolCallingProvider.next_step (OpenAI Responses API, store=false) ---------------+
   |     |  model: ask for NINFA facts through the closed catalog, OR give the final structured answer      |
   |     +---------------------------------------------------------------------------------------------+
   +--> ToolExecutor: validate (typed, extra=forbid) -> authorize (domain policy) -> handler -> Observation
   |        handlers read existing services (DataOverviewService, DecisionMemoryService, AskDecisionContextBuilder, repositories,
   |        the Product Knowledge Registry): a closed read model, never a row, never SQL
   v
validate_model_answer_core -> numeric grounding guard -> completeness check -> (one rewrite, no tools) -> result
   v
MiaConversationService.record_exchange    (only ANSWERED / INSUFFICIENT_CONTEXT turns; the person's own text only)
```

Enforced in code, never requested of the model: no generic data tool; read-only (a test runs every tool under a database that raises
on INSERT/UPDATE/DELETE); no vendor in the application (one adapter, no SDK of its own); bounded loop; fail-closed answers; metadata-only
logging.

## 2. Audit of the legacy Mia V3 branch

`feature/mia-v3-company-intelligence` (3 commits of 9 Oct 2026, tip `3ba2d35`) sits on a base 174 commits behind `main`. It was
audited read-only and **not** rebased, cherry-picked or modified.

| Legacy element | Class | What was done |
|---|---|---|
| `gateway/tool_protocol.py`, a neutral tool-calling port | **adapt** | kept the shape; added the reasoning level, page context, summary and an opaque provider state |
| `anthropic_provider` tool-calling step | **obsolete** | Mia's model is OpenAI's; no Anthropic code was recovered |
| `orchestrator.py`, bounded loop, one correction, fail closed | **adapt** | rounds and calls capped separately, reasoning policy, content-free metrics |
| `grounding.py`, `completeness.py`, `periods.py` (pure) | **reuse** | ported with their tests (103) plus: digits of an identifier are never a figure |
| `tools/base.py`, typed args, authorize-before-run, no write | **adapt** | `ToolRuntime` now carries the registry, the page context and the memoised Dati overview |
| `access.py`, `DomainAccessPolicy` | **reuse** | plus a `PRODUCT` domain |
| 8 tools over `HomeDataService` | **rewrite** | `HomeDataService` changed in 174 commits and the Dati overview is now the canonical read model (coverage, provenance, observed vs reconstructed); 23 tools |
| `knowledge.py`, company knowledge providers | **replaced** | the Product Knowledge Registry plus context tools |
| conversation: one live thread per (workspace, property, user), 12 h idle | **rewrite** | many conversations with ids, 60-day retention, deterministic summary |
| `0014_mia_conversations` | **obsolete number** | recreated as `0017` on the real head; the legacy 0014 never reached `main`, so there is no clash |
| instructions tuned to Anthropic, with the rules learned in the smoke tests | **adapt** | rewritten for the new product; the lessons are kept (numbers literal, no recalculation, data as data, the list of what NINFA lacks) |
| routes `/mia/messages`, `/mia/conversation` | **adapt** | `/mia/messages`, `/mia/conversations` (list, get, delete), `ui_context` |
| `mia-home.tsx` server-conversation wiring | **adapt** | re-done on the current Home; plus a minimal launcher on the other pages |
| `test_mia_*` | **ported / rewritten** | pure ones ported; the rest written against the new design |
| `mia-v3-company-intelligence.md`, ADR 0030 | **superseded** | by this document and ADR 0055 |

## 3. OpenAI

* **Responses API**, model `gpt-6.1-sol` (`MIA_OPENAI_MODEL`), `store=false`, `include=["reasoning.encrypted_content"]`, function tools
  (`strict` off: NINFA's typed models validate and say which argument is wrong), `parallel_tool_calls`, strict `json_schema` final answer
  whose `grounding_refs` is an enum of this turn's refs. No web search, no retrieval, no `previous_response_id`, no `user` or
  `safety_identifier`. `gpt-6.1-sol` accepts `low`/`medium`/`high`, which is the policy's whole range.
* **Shared with Smart Import, not copied:** the client builder (`build_openai_client`: key, `OPENAI_BASE_URL`, `OPENAI_DATA_RESIDENCY`,
  timeout, `max_retries=0`), the failure classification (`classify`, one stable `FailureKind` word, never the vendor's message), the
  retry rule (429, 5xx, a dropped connection; never a timeout, a quota, a refusal), the logger silencing.
* **Mia's own:** `MIA_PROVIDER` (`unconfigured` | `openai`), `MIA_OPENAI_MODEL`, `MIA_OPENAI_TIMEOUT_SECONDS` (40 s per call). The
  turn deadline is 90 s.
* **Reasoning policy** (`policy.py`, deterministic, tested on the product owner's own questions): LOW for "dove trovo...", "cos'è...",
  "come cambio...", "che differenza c'è..."; MEDIUM by default; HIGH for analysis wording or two or more areas in one question,
  and for any turn that consulted three or more areas. A LOW question that needed numbers is raised to MEDIUM.
* **No streaming in V1.** The full answer must pass the numeric and leak checks before anything leaves; streaming unvalidated text would
  defeat them. The UI shows "Mia sta analizzando…".

## 4. Tool layer (23 tools)

| Area | Tool | Domain | Answers |
|---|---|---|---|
| Product | `search_ninfa_knowledge`, `get_page_help`, `get_feature_explanation`, `get_ninfa_glossary` | product | where a thing is, what it means, how to do it, only what exists in this version |
| Context | `get_current_property_context`, `get_data_status` | company / areas | name, time zone, business date, rooms, the page hint; analysis state, per-area coverage, last import per domain, whether the latest delivery was new (also the answer to "perché oggi non ho Decision?") |
| Oggi, Decisioni | `get_today_summary`, `list_decisions`, `explain_decision` | areas | feed state and per-area outcome; the engine's order; Expected / Actual / Delta / estimated impact / data used / limits through the same whitelist as the Decision Ask, in plain words |
| Revenue | `get_occupancy_revenue`, `get_pickup`, `compare_windows` | revenue | occupancy, rooms, room revenue on the books, ADR, capacity state, over-capacity, night rows; NINFA's pickup with the "no new data is not zero" caveat; 7 vs 30 nights vs a week ago |
| Distribution | `get_distribution`, `get_channel_breakdown` | distribution | direct vs OTA, the reference, history vs data-quality insufficiency; channel weights with their denominators |
| Costs | `get_cost_metrics`, `get_cpor` | costs | last concluded month, categories, change; cost per occupied room with the observed / reconstructed basis |
| Staff | `get_staff_metrics` | labor | planned hours and cost by role, cost-to-revenue, revenue per hour, why a ratio is not computable |
| Imports | `get_import_status`, `explain_import_question`, `get_source_learning_status` | company | the latest imports (kind, status, scope, whether it changed data, failure in plain words); what each Smart Import question means; what each source remembers |
| Structure | `get_property_profile`, `get_room_inventory`, `get_connected_sources` | company | the real profile (no demo values), the room inventory and where to change it, the five source cards |

The requested capabilities not listed by name are merged, not missing: `get_data_coverage` into `get_data_status`;
`get_decision`, `get_decision_evidence`, `explain_decision_inputs` into `explain_decision`; `get_today_decisions` into `list_decisions`;
`get_revenue_metrics`, `get_booking_metrics`, `get_occupancy` into `get_occupancy_revenue`; `compare_revenue_periods` into
`compare_windows`; `get_direct_vs_ota` into `get_distribution`; `get_cost_categories` into `get_cost_metrics`;
`get_staff_planned_actual`, `get_role_performance` into `get_staff_metrics`; `get_import_summary` into `get_import_status`.

**Observation contract.** Every observation has plain-Italian keys, figures in the form NINFA stores them, `copertura` (how much of what
was asked the figures cover: nights, days, classified room-nights, `completa`), `aggiornamento` (last import as a fact, whether the
analysis of the business date exists, the kind of data), `non disponibile` (a missing value is `None` plus a reason, never `0`),
`note` and grounding refs. The decision and structure tools never hand the model a raw UUID (its digits would otherwise "ground" a
small invented number; the guard also blanks any UUID).

## 5. Product Knowledge Registry (anti-drift)

222 entries (108 features, 33 states, 25 terms, 22 workflows, 19 metrics, 9 subsections, 6 sections) written from the shipped
code and copy. Each carries machine-verifiable anchors (487 in all: 300 shipped copy strings, 97 enum members, 42 API routes, 37
documents, 6 page routes, 5 Dati tabs). `test_mia_knowledge_registry` checks every anchor and the coverage in both directions:
"obsolete knowledge: <id> anchors a route that no longer exists" and "missing knowledge: <route> has no entry". It covers every page
route, every Dati tab, every sidebar item and every API route group. Search is deterministic and lexical (no model, no network).

**What the registry does not guarantee:** an entry whose anchors still exist but whose description became wrong (for example a button
that is not wired today) is not detected. Rule thresholds (the pickup drop, the occupancy gap, the comparable months) are deliberately
not in the entries: they are versioned and would go stale.

## 6. Page-aware Mia

Each screen publishes one small, closed object (route, section = the Dati tab, `period_days`, `decision_id` on the Decision detail);
the launcher and the Home send it as `ui_context`. The server drops whatever it cannot verify. `selected_metric` and `import_id` are
accepted and validated, but no screen publishes them yet (no screen has a selected metric or import).

## 7. Conversations

`mia_conversations` (migration `0017`): many per (workspace, property, user); composite foreign keys to the property (`RESTRICT`) and to
the membership (`CASCADE`); at most 200 stored entries by CHECK (60 kept); 20 per person and property; 60 days idle. The model sees the
last 10 messages (8,000 characters at most) and a deterministic summary (14 lines at most) of the rest: earlier questions and tool
names, never an answer or a figure, headed "not facts about the data". A refused, unavailable or failed turn is not recorded.

## 8. Data safety

* **Isolation.** A conversation id is matched together with workspace, property and user; another person's, another property's and
  another workspace's id are the same 404 as a missing one (`test_mia_api`, `test_mia_conversation`).
* **PII.** The tools return aggregates. File and source names (user text) go through the same text hygiene Smart Import applies to a
  cell (emails, phones, long digit runs, instruction-looking text) and are labelled as data. The live acceptance plants canary guest
  names, emails and phones and checks that none is in any request body or log line.
* **Prompt injection.** The question is untrusted; the history, the page, the tool results, file and source names are data. A refusal
  classifier stops an injection phrase, an action or a personal-data request before the model; the policy tells the model that data is
  never an instruction; the orchestrator refuses an unknown tool and a malformed argument without running anything.

## 9. Failure behaviour

Provider down, quota, timeout, refused key, an invalid or ungrounded answer, a missed deadline: `UNAVAILABLE`, HTTP 200, nothing recorded,
the failure kind in the log, no vendor text anywhere. The UI says "Al momento non riesco a completare l'analisi con Mia. I dati NINFA
restano disponibili normalmente." Nothing else in NINFA depends on the route.

## 10. Observability and cost

One log line per turn (`mia_turn`): the internal conversation id, status, model and tool calls, tool failures, whether it was corrected,
the reasoning levels, input / output / reasoning tokens, elapsed time, the failure kind. Never the question, an argument, a tool
payload, the answer or a chain of thought. Cost is measured by the live runs (below); no price is invented: the report says "cost
unavailable" when none is typed, and uses the list-price assumption of the Smart Import benchmark ($2.00 / $10.00 per million
tokens, read on the web, not returned by the API) when it is.

## 11. Known limitations

* **No past nights.** Bookings are read forward from the analysis day (the Dati page's own 7- and 30-night windows) and a week back for
  the pickup; a night before the analysis day is "not available".
* **Planned labor hours only.** The Dati view never reads actual hours, so Mia says they are not available.
* **No new-data flag in the overview.** `get_data_status` reads whether the latest booking delivery was new; `get_pickup` always carries
  the caveat instead.
* **Two Italian vocabularies** exist in the codebase (the Dati page says "Governanza", the Decision labels say "Housekeeping"); the tools
  use the page's words and accept both.
* **The registry cannot detect a description that became wrong** while its anchors stay valid.
* **No streaming, no web, no actions.** Writes (inventory, remembered answers, imports) need a future, explicitly confirmed action tool.
* **`observation.kind`** distinguishes a fact from product knowledge; the finer internal split "deterministic calculation" is not
  carried as a separate label.
* **The V2 closed-intent `/ask`** (Anthropic) and its frontend client remain in the codebase, unused by the UI.
* **Reasoning replay.** The adapter returns the encrypted reasoning items of a turn with the next call; in the live runs the model produced
  none at these effort levels, so that path is covered by the adapter tests against the real SDK but was not exercised live.
