# 0019 — Authentication & Session V1: first-party email+password, opaque server-side sessions

## Context

Gate 12 (ADR 0018) shipped the Decision API behind a deliberately fail-closed seam:
`app.core.auth.get_current_principal` always raised 401 in production, because no credential store
or session mechanism existed yet. Gate 13 fills that seam in for real, without touching any of
Gate 12's own routes or their dependency wiring.

## Decision

1. **First-party auth for V1, not a third-party identity provider.** NINFA has no existing
   OAuth/OIDC integration, no existing session infrastructure, and the review explicitly asked not
   to choose an external provider in this gate. A first-party email+password flow is the smallest
   real (not stubbed) mechanism that makes `get_current_principal` genuinely resolvable.

2. **`UserCredential` is a separate table from `User`, never a `password_hash` column on `User`
   itself.** `User` (Gate 1) is identity/account metadata reused by every other module
   (`WorkspaceMembership`, `DecisionMemoryService`'s session context, ...); coupling it to exactly
   one authenticator would make a future SECOND authenticator (a service token, a passkey) a
   schema migration on `User` itself instead of a new, independent row.

3. **Argon2id, via `argon2-cffi`.** The OWASP-recommended default for new password hashing, and
   the one dependency the review explicitly pre-authorized if no existing library covered it -
   none did. Manual SHA-256/PBKDF2/bcrypt-by-hand were explicitly ruled out: password hashing has
   enough subtle failure modes (fixed-time comparison, salt handling, work-factor tuning) that
   reimplementing it is its own security review, not a shortcut.

4. **An opaque, server-side session - never a JWT.** A JWT is self-describing and cannot be
   revoked without an additional server-side blocklist (defeating the "stateless" appeal it is
   usually chosen for); this system already has a database and already needs real-time revocation
   (logout, password rotation) as a hard requirement, so a plain server-side session row is
   simpler AND strictly more capable here, not a compromise.

5. **The database stores `SHA-256(raw_token)`, never the raw token.** The raw token already has
   32 bytes of `secrets`-grade entropy; a stolen DB dump must not be directly usable as a session
   token. A slow, salted hash (Argon2) would be the wrong tool here - it exists to slow down
   guessing a LOW-entropy secret (a password), and would only add cost to every authenticated
   request for no benefit against a HIGH-entropy secret that is already infeasible to guess.

6. **`HttpOnly` + `SameSite=Lax`, no client-readable cookie, no `localStorage`.** `HttpOnly` is the
   only way to make a cookie fully unreadable to any JavaScript, including a future XSS in the
   frontend's own code - a token in `localStorage` is trivially exfiltrated by any script that can
   run at all. `SameSite=Lax` blocks the classic cross-site form-POST CSRF vector for free, ahead
   of this codebase having any mutating endpoint to protect (see ADR 0018's own CSRF note,
   restated below).

7. **Absolute 7-day expiry, never sliding.** A sliding expiry means every authenticated request -
   including a plain `GET`- would need to write `expires_at`, defeating Gate 11/12's own "no write
   on read" posture and adding a race on every request. An absolute window is simpler to reason
   about, to audit, and to test, at the cost of a session dying on a fixed schedule regardless of
   activity - an acceptable V1 trade-off with no auto-renew mechanism yet.

8. **No write on an ordinary authenticated read, ever - not even a "last seen" touch.** Consistent
   with Gate 11/12's own read-only guarantees; `AuthSession` intentionally has no `last_seen`
   column at all, so there is no field a future "helpful" change could start writing to.

9. **One generic `INVALID_CREDENTIALS`, never `USER_NOT_FOUND`/`WRONG_PASSWORD`/
   `ACCOUNT_LOCKED`.** Any of those three distinguishable codes would let a client enumerate which
   emails have accounts, whether a specific password is merely wrong (vs the account not existing
   at all), or whether an account is currently locked - three different information leaks for the
   cost of "nicer" error messages nobody but an attacker benefits from.

10. **Dummy Argon2id verification for an unknown email.** Returning 401 instantly for an unknown
    email while a REAL account takes measurably longer (because Argon2 actually runs) is a classic
    timing side-channel for user enumeration. Running a real Argon2 verification against a fixed
    dummy hash - and discarding the result - keeps the two paths' wall-clock cost close without
    ever creating a `UserCredential` row for an email that may not even be real.

11. **Lockout: 5 failures / 15 minutes, per credential.** A round, simple V1 number matching the
    review's own explicit policy - not tuned against any specific threat model, and explicitly NOT
    a substitute for perimeter/IP-level rate limiting (a distributed attacker spreading attempts
    across many accounts is not slowed by a per-credential counter). That gap is documented debt,
    not an oversight.

12. **A password change revokes every existing session for that user.** A rotated credential
    (whether because it was compromised, or simply changed) must not still be usable via a session
    that was minted under the OLD password - otherwise "change your password" would not actually
    revoke access for whoever else might be holding a valid session.

13. **No public `/signup`, `/reset-password`, `/change-password`, MFA, OAuth, or SSO in V1.** The
    review scoped this gate to the minimum real mechanism the Decision API needs; each of these is
    a real, separate design decision (email delivery, token-based reset flows, a second factor, an
    external provider's own trust model) that deserves its own gate, not a rushed addition here.

14. **Future identity provider migration seam.** `get_current_principal` remains the ONE function
    a later gate replaces - to add a real external IdP, SSO, or a separate service-token system for
    machine-to-machine calls - without touching any Decision API route or its dependency wiring,
    exactly as ADR 0018 anticipated when this seam was first drawn.

## Alternatives considered

- **JWT, stateless, no DB session row.** Rejected: revocation (logout, password rotation) would
  need an additional server-side blocklist anyway, at which point the "stateless" benefit is
  already gone and a plain session row is simpler.
- **Storing the raw session token in the database (no hash).** Rejected: a stolen DB dump would
  then directly grant every active session; hashing it costs nothing at lookup time (a plain
  index) and closes that exposure entirely.
- **bcrypt or a hand-rolled PBKDF2/SHA-256 scheme for passwords.** Rejected: Argon2id is the
  current OWASP recommendation and the review's own explicit preference; there was no existing
  password-hashing dependency in this repo to reuse instead.
- **A sliding session expiry (renew on activity).** Rejected for V1: it would require a write on
  every authenticated request, which this codebase has consistently avoided since Gate 11's own
  "no write on read" posture, and would add a race between concurrent requests renewing the same
  session.
- **Distinct login error codes per failure reason.** Rejected: direct user/account-state
  enumeration, for essentially no legitimate benefit to a real user (a wrong password and a typo'd
  email look identical to the person who made the mistake either way).
- **A new `PropertyAccess` table for the session context's own access listing.** Rejected: Gate 1
  has no such primitive, and Gate 12 already established "active `WorkspaceMembership` -> every
  property of that workspace" as this codebase's V1 policy; inventing a second, parallel
  authorization primitive here would fragment that decision rather than reuse it.

## Consequences

- A future gate can wire a real external identity provider, SSO, or a separate machine-to-machine
  token system by replacing only `get_current_principal`'s body - no Decision API route changes.
- A future "forgot password" flow is additive: a new, separate endpoint that (eventually) also
  calls `AuthService.set_password()`, inheriting the same "revokes every session" guarantee for
  free.
- Before any business-mutating endpoint (acknowledge/dismiss/snooze/etc., a later gate) is added,
  an explicit CSRF policy must be designed for it - `SameSite=Lax` alone is not treated as
  sufficient once a mutation exists; this gate defers that design because there is no mutation yet
  to protect.
- A future maintenance job can delete long-expired `AuthSession` rows without any application code
  change - nothing here depends on old rows being physically removed, only on `expires_at` being
  checked at resolution time.
