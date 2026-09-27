# NINFA

Hospitality Decision Intelligence — B2B SaaS. Monorepo.

> **Status: Gate 18 (Ask NINFA Core V1, `ask-ninfa-v1`) — one new endpoint,
> `POST /properties/{id}/decisions/{id}/ask`, the first and only place in this codebase that ever
> calls a language model: ENGINE CALCULATES, AI EXPLAINS. The model sees ONLY an explicitly
> whitelisted `AskDecisionContext` (Decision identity/status, the latest Observation's whitelisted
> facts/evidence/confidence, the Gate 16 recommendation, up to 10 bounded historical observations) -
> never a raw row, never a `decision_id`, never PII, never a workspace/session identifier. A
> provider-agnostic `Protocol` stands between the service and any vendor; NO vendor was selected in
> this gate - the one shipped production implementation always answers `UNAVAILABLE`, on purpose.
> Output is structured and validated (`ANSWERED`/`INSUFFICIENT_CONTEXT`/`UNAVAILABLE`/`REFUSED`,
> `grounding_refs` from a closed vocabulary), a deterministic guardrail refuses execution/PII/
> injection requests before any provider call, and the user's question is treated as untrusted input
> kept structurally separate from the static system instructions and the context. One question, one
> answer - no conversation persisted, zero migration, zero new dependency, no chat UI yet.** Gate 17
> (Recommendation UI V1, `recommendation-ui-v1`) rendered Gate 16's own `recommendation` as one new,
> additive "Cosa puoi valutare" section on Decision Detail, always after the evidence and never
> before it: a primary review action, up to two supporting checks and any risk notes, copy mapped
> from the backend's own closed `action_code`/`risk_notes` (never from `decision_type`, never
> AI-generated). Gate 16 (Recommendation Engine V1,
> `recommendation-engine-v1`) built the data Gate 17 renders and Gate 18 now also explains: a
> deterministic, non-AI `recommendation`
> - at most one primary plus two supporting review actions, derived from ONLY a Decision and its
> latest Observation (never a raw row, never a detector re-invocation), `requires_human_review`
> always `true`, a SHA-256 fingerprint, zero persistence. Gate 15 (Decision Detail UI V1,
> `decision-detail-ui-v1`) made every "Oggi"
> card navigate to a real Decision Detail page answering "why does this deserve attention" and
> "how has it evolved": current lifecycle status, five detector-specific evidence adapters, a
> deterministic "Perché NINFA te lo mostra" sentence, and a newest-first, cursor-paginated
> "Evoluzione" timeline over Gate 11's own immutable memory - zero recomputation, zero graphs,
> zero mutation controls. Underneath it:
> the technical base, the multi-tenant data core, the import of booking
> files into canonical bookings, the daily snapshots derived from them (observed vs
> reconstructed), the Expected baselines (a historical level with its confidence, not a forecast),
> two revenue detectors that return typed evaluations, since Gate 6 a workspace-wide supplier
> registry with canonical invoices and lines (no PDF/OCR), since Gate 7 one cost detector (cost per
> occupied room, an operating proxy, one currency at a time), since Gate 8 canonical labor entries
> (minutes, never an employee identity) with one staffing detector reusing Gate 5's own demand
> forecast, since Gate 9 a read-only, in-memory channel classifier and a fifth detector measuring
> OTA concentration, since Gate 10 a pure, database-free engine that ranks every TRIGGERED signal
> deterministically, since Gate 11 a persistence layer that recognises the SAME operational
> problem across many days of observations, resolves it only on an explicit CLEAR, reopens the
> same Decision id on a later TRIGGERED, and keeps every day's Observation immutable, since Gate 12
> four `GET` endpoints (feed, list, detail, history) that read exactly that memory behind a
> server-derived tenant scope, since Gate 13 real login/logout/session-context endpoints (Argon2id,
> HttpOnly opaque session cookie, 5-failures/15-minute lockout, no JWT, no sliding expiry) that
> make Gate 12's own `get_current_principal` genuinely resolvable, since Gate 14 the property's
> own IANA timezone on the Session Context and credentialed CORS for the web origin, and since
> Gate 15 the Decision Detail/History read surface, since Gate 16 the additive recommendation
> block, since Gate 17 the Recommendation UI, and since Gate 18 the `/ask` endpoint described
> above - still no chat UI, no connected AI vendor, no free-form AI-generated text outside Ask
> NINFA's own validated contract, no signup, no password reset, no OAuth/SSO/MFA.

## Layout

| Path                 | What                                                        |
| -------------------- | ----------------------------------------------------------- |
| `apps/web`           | Next.js (App Router, TypeScript strict) — Oggi UI V1         |
| `services/api`       | FastAPI modular monolith, SQLAlchemy 2, Alembic             |
| `services/worker`    | Background worker (Procrastinate on PostgreSQL)             |
| `packages/contracts` | Minimal shared TypeScript types (health, auth session, decision feed, recommendation) |
| `docs/`              | Architecture, ADRs, local development guide                 |

## Quick start

```bash
npm run setup                 # npm install + uv sync
cp .env.example .env          # then fill in real values (never commit .env)
npm run db:migrate            # after the database exists (see the local development guide)
npm run dev:api               # http://127.0.0.1:8000/api/v1/health
npm run dev:worker
npm run dev:web               # http://127.0.0.1:3100
```

Quality gates: `npm run test`, `npm run lint`, `npm run typecheck`, `npm run build`.

## Documentation

- [Local development](docs/development/local-development.md) — prerequisites, setup, all commands
- [Architecture v1](docs/architecture/architecture-v1.md) — responsibilities, principles, what is *not* built yet
- [Data model v1](docs/architecture/data-model-v1.md) — entities, tenant integrity, delete policy, indexes
- [Booking data v1](docs/architecture/booking-data-v1.md) — canonical booking, mapping memory, import pipeline, guarantees
- [Booking snapshots v1](docs/architecture/booking-snapshots-v1.md) — room inventory, observed vs reconstructed snapshots, on-books metrics
- [Expected engine v1](docs/architecture/expected-engine-v1.md) — historical comparable baselines, statistics, confidence, INSUFFICIENT_DATA
- [Revenue decisions v1](docs/architecture/revenue-decisions-v1.md) — REV_PICKUP_LOW and REV_OCCUPANCY_RISK: curve pairs, five statuses, confidence, revenue gap proxy
- [Cost ingestion v1](docs/architecture/cost-ingestion-v1.md) — supplier registry and resolution, FatturaPA XML and CSV/XLSX invoices, credit notes, categories, atomic import
- [Cost CPOR anomaly v1](docs/architecture/cost-cpor-anomaly-v1.md) — COST_CPOR_ANOMALY: cost per occupied room, lead-time-0 denominator, comparable months, median/IQR, confidence, cost gap proxy
- [Labor ingestion v1](docs/architecture/labor-ingestion-v1.md) — canonical labor snapshots/entries in minutes, no employee identity, mapping memory, atomic import
- [Labor overstaffing v1](docs/architecture/labor-overstaffing-v1.md) — LABOR_OVERSTAFFING: demand forecast reuse, ACTUAL-FIRST comparables, median/IQR, confidence, cost gap proxy
- [OTA dependency v1](docs/architecture/ota-dependency-v1.md) — REV_OTA_DEPENDENCY: 30-day forward window, conservative channel classification, temporal reuse, structural vs rising dependency, confidence
- [Priority Engine v1](docs/architecture/priority-engine-v1.md) — cross-domain ranking of TRIGGERED signals: normalized severity, detector-aware urgency, confidence reuse, fixed actionability, exact-Decimal scoring, deterministic tie-break
- [Decision Layer v1](docs/architecture/decision-layer-v1.md) — persistent Decision identity, cross-day deduplication, OPEN/RESOLVED lifecycle, explicit CLEAR resolution, reopening, immutable observation history, Decision Memory
- [Decision API v1](docs/architecture/decision-api-v1.md) — read-only feed/list/detail/history over the Decision Layer, fail-closed auth, server-derived tenant, cursor pagination, exact Decimal as string
- [Authentication & Session v1](docs/architecture/auth-session-v1.md) — email+password login, Argon2id, opaque server-side session, HttpOnly cookie, lockout, credential provisioning CLI
- [Oggi UI v1](docs/architecture/oggi-ui-v1.md) — authenticated shell, login UI, property selection, property-local "today", four feed states, five decision card types, zero graphs, zero recommendations
- [Decision Detail UI v1](docs/architecture/decision-detail-ui-v1.md) — current lifecycle snapshot, five evidence adapters, deterministic "why" copy, newest-first cursor-paginated history, zero recomputation
- [Recommendation Engine v1](docs/architecture/recommendation-engine-v1.md) — deterministic, non-AI review actions over Decision + latest Observation only, requires_human_review always true, SHA-256 fingerprint, additive on Decision Detail, zero persistence
- [Recommendation UI v1](docs/architecture/recommendation-ui-v1.md) — "Cosa puoi valutare" section on Decision Detail, evidence-first, action_code-keyed static copy, no execute/approve/apply control, no checkbox, no AI aesthetic
- [Ask NINFA Core v1](docs/architecture/ask-ninfa-v1.md) — grounded, single-turn, decision-scoped explanation layer; whitelisted context, provider-agnostic protocol with no vendor selected, structured/validated output, deterministic guardrails, zero persistence
- [Architecture decision records](docs/architecture/adr/)
