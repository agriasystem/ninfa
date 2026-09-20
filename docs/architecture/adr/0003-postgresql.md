# 0003 — PostgreSQL as the single datastore

**Status:** accepted (Gate 0)

## Context
NINFA needs relational integrity, transactions, multi-tenant scoping and eventually analytical
queries over hotel data, plus a reliable job queue.

## Decision
PostgreSQL is the primary and only database (also backing the job queue, see ADR 0005). Access via
SQLAlchemy 2 with the psycopg 3 driver; schema changes only through Alembic. The application uses a
dedicated non-superuser role. Local development uses a native PostgreSQL 18; a Docker Compose
service (host port 5433) is provided as a portable alternative.

## Consequences
- One system to operate, back up and secure.
- Row-level security, partitioning or extensions are deferred until a gate needs them.
- No data warehouse, replica, sharding, time-series or vector database for now.
