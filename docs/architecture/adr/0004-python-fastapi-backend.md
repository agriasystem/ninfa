# 0004 — Python + FastAPI backend

**Status:** accepted (Gate 0)

## Context
The product is data- and rules-heavy (parsing, normalisation, statistics, later AI), which Python
serves best. The API needs typed validation and a machine-readable contract.

## Decision
Python 3.13 (managed by uv), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic. Typed settings from the
environment. The OpenAPI schema generated from Pydantic models is the authoritative API contract;
no code generation is set up yet. Quality tooling: ruff, mypy (strict), pytest.
TypeScript is pinned to 5.9 because typescript-eslint does not yet support TypeScript 7.

## Consequences
- Fast development with validation and docs for free; strict typing enforced in CI.
- Frontend types are hand-written and minimal until a contract strategy is decided in a later gate.
- The synchronous SQLAlchemy engine is used for now; async can be introduced where measured.
