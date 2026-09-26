# Authentication & Session V1 (`auth-session-v1`, Gate 13)

First-party email + password login with an opaque, server-side session. Fills in the fail-closed
seam Gate 12 left (`app.core.auth.get_current_principal`) with a real resolver. See ADR 0019 for
the "why" behind every choice below; this document is the "what" and "how".

## Scope

Three routes under `/api/v1/auth/`: `POST /login`, `POST /logout`, `GET /session`. Plus one
internal CLI, `python -m app.cli.auth set-password`, the only way to give a `User` a password in
V1. Explicitly NOT in scope: public signup, password reset/forgot-password, email verification,
OAuth/SSO/social login, MFA, passkeys, a new RBAC or `PropertyAccess` model, any UI.

## First-party auth: `User` + `UserCredential` + `AuthSession`

`User` (Gate 1) stays identity/account metadata only - it never gained a `password_hash` column.
Two new tables instead:

- **`UserCredential`**: the ONE password authenticator of a `User` (unique `user_id`).
  `password_hash` is a full Argon2id PHC string; `failed_login_count`/`locked_until` implement the
  brute-force policy below; `password_changed_at` moves only on a real password change.
- **`AuthSession`**: ONE server-side session per successful login. `token_hash` is
  `SHA-256(raw_token)`; the raw token itself is never persisted, only ever held by the browser's
  cookie. `expires_at` is set once, at creation, and never moves (no sliding expiry - see below).
  No `last_seen`: an ordinary authenticated `GET` never writes to this table.

Neither table carries a `workspace_id` - a `User` is a global identity (unchanged since Gate 1),
and authentication happens before any tenant is resolved.

## Password security

**Argon2id**, via `argon2-cffi` (the one new backend dependency this gate needed - no existing
library in the repo hashes passwords). `app.modules.auth.passwords` is the ONLY module allowed to
hash or verify one. The library's own tuned default parameters are used as-is; the raw password is
never trimmed, truncated or required to satisfy any composition rule - length is the ONLY
provisioning-time policy (14-128 characters, `app.cli.auth`), enforced at provisioning, never at
login (login must accept whatever was once hashed, verbatim).

### Unknown-user / dummy verification

An email that resolves to no `User`, or a `User` with no `UserCredential` row, never touches
either table. Instead, `dummy_verify()` runs a REAL Argon2id verification against a fixed,
module-load-time dummy hash and discards the (always-mismatching) result - so the wall-clock cost
of "no such account" stays close to a real attempt's, closing the crudest timing side-channel for
user enumeration (not a promise of perfectly constant time - Argon2's own memory-hard design and
this process's scheduling still vary somewhat).

### Rehash-on-login

If `PasswordHasher.check_needs_rehash()` says the stored hash used weaker/older parameters than
this process's current defaults, a successful login re-hashes the just-verified plaintext and
updates `password_hash` in the SAME transaction - the plaintext is only ever available inside that
one successful login, so this is the only place a transparent upgrade can happen without asking
the user to log in again.

## Session model

- **Token**: `secrets.token_urlsafe(32)` (32 bytes / ~256 bits of entropy) - an opaque, structure-
  less random string. Never a JWT, never a container for `user_id`/`workspace_id`/an expiry/any
  claim a client could parse.
- **Storage**: the browser's cookie holds the RAW token; `auth_sessions.token_hash` holds only its
  SHA-256 (64-char lowercase hex, unique). A stolen DB dump is useless as a session token; the
  raw token's own entropy is what actually resists guessing, so a fast general-purpose hash - not
  Argon2's deliberate slowness - is the right tool for this specific lookup key.
- **Expiry**: `SESSION_ABSOLUTE_LIFETIME = 7 days`, set once at creation, ABSOLUTE - never sliding.
  An ordinary authenticated request never re-writes `expires_at`; a session is either still within
  its original 7-day window or it is not.
- **Revocation**: `revoked_at` (nullable). Set once, in place, by logout or by a password
  rotation - never unset.

## Cookie policy

Name: `ninfa_session` (stable, V1). `HttpOnly` (never readable from JavaScript - no
`localStorage`/`sessionStorage`/a JS-readable cookie anywhere in this design), `SameSite=Lax`,
`Path=/`, host-only (no `Domain` attribute - never shared across subdomains implicitly). `Secure`
is configuration-driven (`Settings.session_cookie_secure`, default `True`, i.e. HTTPS-only
everywhere): production REQUIRES it (`Settings` raises if `APP_ENV=production` and it is `False`);
a plain-HTTP local dev environment (or an in-process test - see "Local development" below) must
set it `False` explicitly. `max_age` matches the session's own 7-day absolute lifetime.

The cookie is read/written through exactly one seam per direction: `app.core.auth.
set_session_cookie`/`clear_session_cookie` (write) and `request.cookies.get(SESSION_COOKIE_NAME)`
(read, in `get_current_principal` and `get_current_auth_session`) - never duplicated ad hoc.

## Login

`POST /api/v1/auth/login`, JSON body only (`{"email", "password"}` - never
`application/x-www-form-urlencoded`). Email is normalized through Gate 1's own
`app.core.validation.normalize_email` (via `UserRepository.get_by_email`) - no second
normalization policy invented here.

On success: the failure counter/lock reset, a brand-new session is created (a fresh random token,
never the incoming cookie's value - this is what actually prevents session fixation), any session
the INCOMING cookie already named is revoked (hygiene, not the fixation defence itself), and the
response is the SAME `SessionContextResponse` shape `GET /session` returns.

On failure - unknown email, wrong password, no credential row, or a locked account - the response
is always `401 INVALID_CREDENTIALS`, with the identical message, whichever of those four is
actually true. `USER_NOT_FOUND`/`WRONG_PASSWORD`/`ACCOUNT_LOCKED` are deliberately never
distinguished to the client.

## Brute-force protection V1

Per credential: `MAX_FAILED_ATTEMPTS = 5`, `LOCK_DURATION = 15 minutes`. The 5th consecutive
failure sets `locked_until = now + 15m`. While locked, EVERY attempt (even with the objectively
correct password) still answers `401 INVALID_CREDENTIALS` - never a different code, never a hint
that the password was actually right. A correct login before the 5th failure resets
`failed_login_count`/`locked_until` immediately. After `locked_until` passes, a correct login
succeeds and resets both. An unknown email never creates a `UserCredential` row to lock in the
first place (see "dummy verification" above). Concurrent failed attempts on the SAME credential
are serialized with `SELECT ... FOR UPDATE` (`AuthRepository.get_credential_for_update`) - no
advisory-lock framework, the same posture Gate 11's own `DecisionService` established for a
different table.

**V1 limitation, intentional**: this is per-credential, not per-IP/perimeter. A distributed
attacker spreading attempts across many accounts (never triggering any ONE account's 5-failure
threshold) is not slowed down here - that is infrastructure-level rate limiting, a future gate's
concern, not this one's.

## Session context

`GET /api/v1/auth/session` (and the identical shape on a successful login): `user` (`id`, `email`,
`display_name` - exactly the fields `User` has and no more), `session.expires_at`, and
`workspaces[]` (each with `id`/`name`/`slug`/`role` and its own `properties[]`). Access follows the
EXACT SAME policy Gate 12's Decision API already established: an active `WorkspaceMembership`
grants every property of that workspace - no `PropertyAccess` primitive invented for this gate
either. This is deliberate: a future "Today" UI needs to know who is logged in and which
workspace/property to open WITHOUT a temporary, throwaway API Gate 14 would otherwise have to
build just to answer that.

## Principal resolution (`get_current_principal`)

    HttpOnly cookie -> raw token -> SHA-256 -> AuthSession lookup (unrevoked, unexpired)
    -> active User lookup -> AuthenticatedPrincipal(user_id)

No cookie, a token that hashes to no row, an expired or revoked session, or a `User` that no
longer exists/is inactive: all answer the identical `401 AUTHENTICATION_REQUIRED` - the same
posture Gate 12 already used for "missing" vs "unauthorized". This function is a FastAPI
dependency; the Decision API's four routes (Gate 12) were NOT modified to accept it differently -
they still depend on exactly `get_current_principal`, which is now genuinely resolvable instead of
unconditionally failing. No header (`X-User-Id`, `Authorization: Bearer`, or any other) is ever
accepted as an alternative; that boundary is enforced by both the source (nothing in
`app/core/auth.py`/`app/api/v1/auth/` reads any such header) and a runtime test
(`test_auth_security.py`).

## Logout & revocation

`POST /api/v1/auth/logout`: revokes the session the cookie names (if any - a missing, malformed,
expired or already-revoked cookie is a silent no-op, never an error) and clears the cookie.
Prefers `204 No Content`. Logging out one session never revokes the user's OTHER sessions.

**Password rotation revokes every session.** `AuthService.set_password()` (used by both the CLI
and, implicitly, by any future password-change primitive) revokes ALL of a user's un-revoked
sessions in the same transaction as the credential update - a credential a browser is not supposed
to be using anymore must not still be trusted through an old session either.

## Credential provisioning CLI

    python -m app.cli.auth set-password --email user@example.com

The ONLY way to give a `User` a password. Reads via `getpass.getpass` (never a CLI argument, never
required as an environment variable, never echoed), asks for confirmation, enforces the 14-128
character policy, and FAILS if the email names no existing `User` - it never creates a `User`,
`Workspace` or `WorkspaceMembership`. A password change resets the failure/lock state and revokes
every existing session (see above).

## Security & privacy

No password, raw session token, password hash, or login request body is ever logged (checked at
runtime, not just by review). No response - login, logout, session context, or any error body -
ever contains a credential hash, a raw token, or a raw password; the generated OpenAPI schema
declares no field named after a credential/session internal. `Cache-Control: no-store` on every
`/auth/*` response.

## Limitations (intentional, documented debt)

- **No public signup, password reset, or email verification** - provisioning is CLI-only, by an
  operator, for a `User` that already exists.
- **No MFA, passkeys, OAuth/SSO** - V1 is email + password only.
- **No per-IP/perimeter rate limiting** - brute-force protection is per-credential only (see
  above); a WAF/perimeter layer is future infrastructure, not this gate.
- **No session cleanup job** - an expired `AuthSession` row stays in the table (unusable, but
  present) until a future maintenance job removes it. No scheduler was added for this gate.
- **CSRF**: today's business API is GET-only, and the cookie is `SameSite=Lax` + `HttpOnly`, which
  already blocks the classic cross-site form-POST CSRF vector; `POST /auth/login` only accepts
  JSON (never a form-urlencoded body a plain HTML `<form>` could submit cross-site without
  JavaScript). **Before the first business MUTATION** (acknowledge/dismiss/etc., a later gate), an
  explicit CSRF policy (a double-submit token, a custom header requirement, or similar) is
  required - this gate does not build that framework today, because there is no mutating endpoint
  yet for it to protect.
- **Future identity provider migration seam**: `get_current_principal` is the ONE function a
  future gate replaces to add a real session cookie issued by an external IdP, a JWT-based service
  token system, or SSO - no other route or dependency needs to change.
