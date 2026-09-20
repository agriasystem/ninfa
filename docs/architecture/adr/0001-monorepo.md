# 0001 — Monorepo

**Status:** accepted (Gate 0)

## Context
NINFA has a web frontend, a Python API, a worker and shared contracts, developed by a small team
that must change them together. Cross-repository coordination would add overhead with no benefit.

## Decision
One Git repository: `apps/web`, `services/api`, `services/worker`, `packages/contracts`, `docs`.
JavaScript uses npm workspaces (one lockfile, no extra tool); Python uses a uv workspace (one
lockfile, one virtualenv) with two members.

## Consequences
- Atomic changes across frontend, backend and docs; a single CI.
- Two package ecosystems live side by side; root scripts (`package.json`) hide the difference.
- No build orchestrator (Nx, Turborepo, Bazel) until a real need appears.
