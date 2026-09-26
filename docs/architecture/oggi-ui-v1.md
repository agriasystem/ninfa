# Oggi UI V1 (`oggi-ui-v1`, Gate 14)

The first real, visible product surface of NINFA: an authenticated shell around a single
question - "what deserves my attention today?" - answered by the Decision API (Gate 12) through
a real session (Gate 13). Complexity stays inside the backend; the UI stays deliberately narrow.

## Philosophy

Everything Gate 0-13 built (DATA → EXPECTED → DETECT → CONFIDENCE → PRIORITY → DECISION MEMORY →
DECISION API → AUTHENTICATION) already decided what matters and in what order. Gate 14 adds
nothing to that decision: it is a rendering and authentication layer only. NINFA must not look
like a PMS, a BI dashboard, an admin panel or a spreadsheet - the user never interprets a chart to
understand what is happening. The MVP keeps the choice made from the start: **zero graphs**.

## Authenticated shell

`components/app-shell.tsx` is the whole authenticated frame: the `NINFA` wordmark (a plain
typographic mark - no logo asset exists yet, see "Limitations"), the property selector, the
account email and a single "Esci" (logout) action. Nothing else. There is deliberately no
Analytics/Revenue/Costi/Personale/Settings/Notifications/"Ask NINFA" navigation - those features
do not exist yet, and a placeholder link to them would misrepresent the product.

`components/auth-gate.tsx` wraps every authenticated route. It renders a neutral, empty loading
shell while the session status is unknown, and only ever renders children once a real session
has been confirmed - the app never shows authenticated content for even one frame before that
answer is known. Once the bootstrap call resolves to "unauthenticated", it defers to a caller-
supplied redirect (to `/login`) from inside a `useEffect`, never during render itself.

## Login UI

`components/login-form.tsx`: email + password, one CTA ("Accedi"). No "Registrati", no "Password
dimenticata", no "Accedi con Google", no "Remember me" - none of those exist yet either.
`autocomplete="email"` / `autocomplete="current-password"` are set explicitly. A submit:

- disables the button and relabels it ("Accesso in corso…") for the duration of the request,
  blocking a double submit (a disabled `<button>` does not receive a second click at all);
- clears the password field afterwards in every case, success or failure - it is never logged,
  never persisted, never put in a URL;
- on success, adopts the `SessionContextResponse` **returned directly by the login response**
  (`useSession().setSession(...)`) rather than immediately re-fetching `GET /auth/session` - the
  two endpoints return the identical shape (Gate 13's own design), so re-fetching would only be a
  redundant round trip with a race against itself;
- on failure, shows exactly one of two Italian strings: the backend's own generic
  `INVALID_CREDENTIALS` message ("Email o password non corretti.") or a generic retry message for
  anything else (network, 500, misconfiguration) - the backend deliberately never distinguishes
  "unknown email" from "wrong password" from "account locked" (see `auth-session-v1.md`, "why one
  generic error"), and the frontend must not defeat that by inventing a more specific reason.

## Property selection

The authenticated `SessionContextResponse` (Gate 13, extended below) is the ONLY source of which
properties exist for a user - there is no free-text/UUID field anywhere. `lib/session/
properties.ts` implements the exact policy the spec requires:

- **0 properties** → `AppShell` renders a dedicated empty state instead of the feed;
- **1 property** → selected automatically, no selector rendered at all;
- **>1 properties** → `components/property-selector.tsx` (a native `<select>`) is shown.

The selected property is carried in the URL (`/oggi?property=<uuid>`), never in `localStorage` -
`app/oggi/page.tsx` reads/writes it via `next/navigation`'s `useSearchParams`/`useRouter`. An
unknown or foreign id in that query parameter is never trusted: `resolveSelectedProperty` falls
back to the first accessible property (ordered by slug, exactly as the backend already orders
them) and `components/oggi-screen.tsx` corrects the URL to match via the very same callback the
selector itself uses - there is no separate "invalid id" code path to keep in sync. The backend's
own `resolve_property_scope` (Gate 12) remains the last real authorization barrier regardless of
what the client believes: a 404 from the feed endpoint (see "Error handling") is treated as "this
property is no longer valid" and triggers exactly the same re-resolution.

## Property timezone

"Oggi" means **today in the property's own timezone**, never `new Date().toISOString().slice(0,
10)` (UTC) and never the browser's timezone. `Property.timezone` already existed as a real,
non-nullable, IANA-validated column since Gate 1 (`app/modules/properties/models.py`, default
`"Europe/Rome"` for new rows only - existing rows always carry a real value); it was simply never
exposed on the Session Context. Gate 14 adds `timezone` to `PropertyAccess`
(`app/api/v1/auth/schemas.py`) additively - no migration, no change to any other field - and
populates it in `build_session_context` from the real row. `test_auth_session_endpoint.py` gained
a test asserting a *non-default* timezone value round-trips correctly, so the field cannot be
hardcoded to the model's own default and pass by accident.

`lib/date/property-date.ts` computes the local calendar date from `Intl.DateTimeFormat.
formatToParts` (no external date library): `propertyLocalDate(now, timeZone)` returns
`YYYY-MM-DD`, and `formatPropertyLocalDateItalian(now, timeZone)` renders the same instant as
capitalised Italian prose ("Venerdì 26 settembre"). Both take the exact same `(now, timeZone)`
pair, so the machine-readable `as_of` sent to the API and the human-readable heading can never
disagree. Tests cover both UTC-boundary directions (a positive-offset property rolling to the
*next* day, a negative-offset one staying on the *previous* day) and a same-clock-time, different-
season DST comparison (Europe/Rome in January vs. July) to prove the real IANA offset of that
specific day is used, never a fixed constant.

## Explicit `as_of`

`GET /api/v1/properties/{propertyId}/decision-feed?as_of=<property-local-today>` - the query
parameter is always computed explicitly by `components/today-screen.tsx` from the resolved
property's own timezone, exactly as Gate 12's own contract requires (a missing/server-clock
`as_of` is not a valid request at all).

## Feed-state mapping

The four `FeedState` values (Gate 12) are rendered as four **visually and semantically distinct**
branches of `components/feed-state-view.tsx` - a plain `switch` on `feed.feed_state`, one JSX
branch per value, each carrying its own `data-feed-state` marker and its own border/background
accent (never colour alone - the heading text always differs too):

| State | Heading | Copy |
| --- | --- | --- |
| `NOT_PROCESSED` | "Analisi non ancora disponibile" | calm, non-alarming - never "all clear" |
| `DATA_QUALITY_LIMITED` | "Analisi parziale" | states *how many* checks lacked data/were suppressed, never calls it a technical error |
| `NO_ACTION_REQUIRED` | "Tutto sotto controllo" | the **only** branch allowed to say this |
| `ACTION_REQUIRED` | "Decisioni di oggi" | renders `DecisionList` |

The golden test suite (`golden/oggi-golden.test.tsx`) renders all four states from hand-authored
fixtures and asserts this mutual exclusivity directly, plus the "Tutto sotto controllo" placement
rule specifically.

## Top-5 presentation

The API already returns every triggered candidate, ordered `priority_rank ASC`
(`DecisionRepository.feed_rows()`, Gate 12). `components/decision-list.tsx` does exactly one
thing beyond rendering: `items.slice(0, 5)` - a presentation limit, never a backend change, never
a re-sort, never a re-filter. When more than 5 candidates exist, a single discreet line ("+ N
altre decisioni") is shown, with no link to a page that does not exist yet.

## Decision cards, five types

`lib/decisions/card-view-models.ts` is the explicit adapter layer: one function per
`decision_type`, reading ONLY the exact fact keys Gate 12's own whitelist
(`app/api/v1/decisions/serializers.py::_FACTS_WHITELIST`) allows for that type, never
`Object.entries(facts)`, never a raw JSON dump, never an invented field. Static Italian titles
(`lib/copy.ts::decisionTypeTitles`) replace the machine codes:

| `decision_type` | Title |
| --- | --- |
| `REV_PICKUP_LOW` | Pickup sotto le attese |
| `REV_OCCUPANCY_RISK` | Rischio occupazione |
| `REV_OTA_DEPENDENCY` | Dipendenza OTA |
| `COST_CPOR_ANOMALY` | Costo per camera anomalo |
| `LABOR_OVERSTAFFING` | Ore di personale sopra l'atteso |

Every `*_exact`/Decimal-shaped fact is carried as its original STRING through the adapter layer;
`lib/decisions/format.ts` formats it for DISPLAY ONLY (Italian-locale rounding, a `%`/`h`/currency
suffix) - nothing here is ever parsed back into a `number` to re-rank, re-threshold or otherwise
recompute a decision. Percentage-shaped facts (`*_percent_exact`, `*_pp_exact`, `*_share_exact`)
are already on the 0-100 scale server-side (`percent_of()` in each detector's own
`precision.py`), so the formatter never multiplies by 100 again. Confidence is shown as
"Affidabilità N%" from the backend's own `confidence_score` - never bucketed into
Alta/Media/Bassa with a new frontend threshold. An `economic_proxy`, when present, is formatted
as localised money using its own `label`/`currency`, never automatically called "perdita" or
"risparmio".

Every card shows PROBLEM + EVIDENCE, never a recommendation - "Abbassa il prezzo", "Riduci il
personale" and similar phrasing are explicitly checked absent by tests.

## No graphs

No chart library, no `<svg>`/`<canvas>` element, anywhere in this Gate's components - checked
directly by component tests (`decision-card.test.tsx`, the golden suite).

## API client

`lib/api/client.ts` centralises every HTTP call behind `apiRequest<T>()`: `credentials:
"include"` and `cache: "no-store"` on every request, JSON body serialisation, and a stable
`ApiResult<T>` union (`{ ok: true, data }` or `{ ok: false, status, code, message }`) parsed from
the Gate 12/13 error envelope - never a raw `Response`, a stack trace, `details` or `request_id`
reaches a component. `lib/api/auth.ts` and `lib/api/decisions.ts` are thin, typed wrappers over
it (`login`/`logout`/`getSession`, `getDecisionFeed`) - no `fetch()` call exists anywhere else in
the codebase.

## Auth cookie handling

The session cookie (`ninfa_session`, Gate 13) is `HttpOnly` - no line of frontend code reads,
writes or even references its value. There is no `localStorage`/`sessionStorage` token, no
`Authorization: Bearer` header, no `X-User-Id` header. `lib/session/session-context.tsx`
(`SessionProvider`/`useSession`) is the one place that tracks "am I logged in": on mount, it calls
`GET /auth/session` once (the auth bootstrap); `setSession` adopts the response of a successful
login directly; `logout` calls `POST /auth/logout` then clears local state regardless of the
network result, since the cookie is cleared server-side either way and there is nothing sensitive
left in memory to protect by waiting.

### CORS / transport topology

In local development, the web app (`http://127.0.0.1:3100`) and the API
(`http://127.0.0.1:8000`) are different origins, so the session cookie can only cross that
boundary if the browser is told the response may be read WITH credentials. `CORS_ORIGINS` already
existed as a configured, explicit allowlist (`app/main.py`'s `CORSMiddleware`, present since an
earlier gate for the health check); Gate 14 adds the one thing that allowlist did not yet need:
`allow_credentials=True`. `allow_origins` is always an explicit list (`Settings` forbids a literal
`"*"` in production, and Starlette itself never emits a literal `"*"` alongside credentials even
if a non-production list contained one - it echoes the request `Origin` instead), so this never
combines a wildcard with credentials. No same-origin proxy/rewrite exists in this repository, so
this explicit-origin CORS configuration is the real, minimal fix the actual topology needs - not
a duplicate of something already handled elsewhere.

### Production cookie assumption

Gate 13's session cookie uses `SameSite=Lax`. V1's architecture therefore assumes the web app and
the API are **same-site** in production (e.g. `app.ninfa.io` and `api.ninfa.io`, or a single
origin) - `SameSite=Lax` still permits the cookie on top-level navigations, but this is not a
general cross-site credentialed-fetch solution. This is a documented assumption, not changed by
this gate: no `SameSite` policy change is warranted by anything Gate 14 introduces.

## Loading / errors

- **Session loading** (`AuthGate`): a neutral, shell-only empty state - no spinner, no flash of
  authenticated content.
- **Feed loading** (`TodayScreen`): a simple three-line skeleton (`prefers-reduced-motion` turns
  off its shimmer animation), never a large spinner.
- **401** anywhere → the session becomes `unauthenticated` and `AuthGate` redirects to `/login`.
- **404 `PROPERTY_NOT_FOUND`** on the feed call → treated as "this property is no longer valid":
  `TodayScreen` calls `onPropertyInvalid`, which triggers a session refresh and property
  re-resolution, showing the same neutral loading state meanwhile - never the raw backend error.
- **Network failure / 500 / any other error** → one generic Italian sentence ("Non siamo riusciti
  a caricare l'analisi. Riprova.") with a single "Riprova" action, which only ever repeats the SAME
  `GET` - it never triggers a detector run, a Decision sync or any other write.

## Responsive / accessibility

Layout is verified at 1440×900 (desktop), 1024×768 (laptop) and 390×844 (mobile) via a manual
checklist (see "Limitations" - no browser-automation tool exists in this repository yet, and one
is deliberately not added for this gate) plus what the component/CSS-class tests already assert
(e.g. decision-card facts collapse to a single column under 480px). Accessibility: every input has
a real `<label>`; focus is always visible (`:focus-visible`, never removed); the property selector
is a native, keyboard-operable `<select>`; headings follow a real `h1`/`h2`/`h3` hierarchy; feed-
state and login-error regions use `role="alert"`/`aria-live` where the content can change without
a click; no state is communicated by colour alone (every semantic state also has distinct copy and
an icon-free but distinct visual treatment).

## Limitations (intentional, documented debt)

- No Decision Detail page, no Ask NINFA, no AI-generated text, no recommendation engine.
- No signup, password reset, OAuth or MFA (unchanged from Gate 13).
- No i18n framework - copy is centralised (`lib/copy.ts`) but hardcoded to Italian.
- No dedicated E2E/browser-automation suite (Playwright or similar) - visual acceptance at the
  three target viewports is a manual checklist plus component/CSS-level tests.
- No real NINFA logo asset - the shell uses a plain typographic wordmark until a brand asset is
  frozen in the repository.
- `lib/health.ts`/`components/health-status.tsx` (Gate 0) are no longer wired into any page (the
  root route now redirects based on auth state) but were left in place, untouched and still
  tested, rather than deleted - they are not part of this gate's scope either way.
