# 0006 — Tenant integrity enforced by the database

**Status:** accepted (Gate 1)

## Context
NINFA is multi-tenant: the workspace is the tenant boundary and one user may belong to several
workspaces. Business data will be sensitive (bookings, costs, payroll-related data) and a
cross-tenant leak is the worst failure the system can have. Isolation must not depend only on
frontend filters, nor only on every developer remembering a `WHERE workspace_id = ...` forever.

Relationships are the subtle part. With ordinary foreign keys, a data source of workspace A can
point at a property of workspace B, and every constraint is satisfied:
`data_sources.property_id → properties.id` only checks that the property exists.

## Decision
1. **`workspace_id` is explicit on every tenant-owned table** (memberships, properties, data
   sources, import jobs, import files), never derived through joins. This makes tenant scoping
   trivial to apply, to test and to index, and it is what future row-level security policies
   would use.
2. **Composite foreign keys carry `workspace_id`**, so that a child row can only reference a
   parent of its *own* workspace:
   ```
   data_sources (workspace_id, property_id)                 → properties  (workspace_id, id)
   import_jobs  (workspace_id, property_id, data_source_id) → data_sources (workspace_id, property_id, id)
   import_files (workspace_id, import_job_id)               → import_jobs (workspace_id, id)
   ```
   Each parent gets a unique constraint on the referenced column set (`(workspace_id, id)`, ...). It
   is redundant with the primary key, but PostgreSQL requires a unique target for a foreign key.
   All these columns are `NOT NULL`, so the default `MATCH SIMPLE` semantics cannot be sidestepped
   with a NULL.
3. **One key for two rules on import jobs.** Referencing `(workspace_id, property_id, data_source_id)`
   also forces the job's property to be its data source's own property, a stricter and more useful
   invariant than "same workspace" for the same cost.
4. **No separate FK from child tables to `workspaces`.** The chain
   `import_files → import_jobs → data_sources → properties → workspaces` already guarantees the
   workspace exists. A second FK would only duplicate checks.
5. **Application layer**: `TenantContext` is mandatory to build a tenant-owned repository, which puts
   the `workspace_id` in every query and has no method taking a workspace argument. Parents are
   resolved inside the tenant first; the database keys remain the backstop.
6. The database rules are tested by bypassing every application safeguard (bare ORM and raw SQL),
   plus a control experiment showing that a plain single-column FK would accept the same mistake.

Rejected alternatives: single-column FKs plus a trigger per table (more code, easy to forget on a new
table, harder to reason about); relying on repositories only (a single missed filter or a hand-written
query becomes a leak); PostgreSQL row-level security now (valuable, but it needs an authenticated
tenant context that does not exist until the auth gate; the schema is ready for it).

## Consequences
- A cross-tenant relationship cannot exist, even through a bug, a manual SQL fix or a future job.
- Every new tenant-owned entity must follow the same pattern (checklist in `data-model-v1.md`).
- Some redundant unique indexes and wider foreign keys; a small, constant write cost.
- Changing a row's `workspace_id` is blocked while children reference it; moving data between
  workspaces will need an explicit, deliberate procedure.
- Reads must still be scoped by `workspace_id`: foreign keys protect *relationships*, not queries.
  Repositories (and later RLS) cover that side.
- Authentication/authorization, which decide *which* workspace a caller may use, come in a later gate.
