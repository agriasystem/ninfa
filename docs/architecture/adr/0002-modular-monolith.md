# 0002 — Modular monolith

**Status:** accepted (Gate 0)

## Context
The domain (properties, bookings, invoices, labor, decision engine) is still being discovered.
Distributed systems would add cost (deployment, consistency, observability) before any value.

## Decision
One deployable backend organised in modules under `app/modules/`, with a separate worker process
from the same codebase. No microservices, Kubernetes, message broker, event bus, CQRS or event
sourcing. Module boundaries are kept by convention: a module exposes functions, not its tables.

## Consequences
- Simple local development, deployment and transactions.
- Discipline is needed to keep modules decoupled; boundaries can be enforced later with tooling.
- Extracting a module into a service stays possible if measured needs justify it.
