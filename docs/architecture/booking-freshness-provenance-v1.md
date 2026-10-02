# Run input provenance & booking freshness v1 (Gate 23B)

## What this closes

Gate 21A/21B wired real orchestration; Gate 22 made WHICH domains a run attempted visible. Neither
gate recorded WHERE a run's booking facts came from, freshness-wise. `ImportJob.finished_at` is
the authoritative completion instant of a successful import, but nothing reading Oggi could ever
see it: a property can have more than one BOOKINGS `DataSource`, `DecisionRun` never recorded
which one a run used, and any attempt to show "freshness" by querying "the latest import" live,
at display time, would be actively unsafe - it would describe the CURRENT state of the world, not
the state the run was actually computed against. Two dangerous scenarios this closes:

1. Import A completes, a run uses A, import B completes later, the operator opens Oggi - Oggi
   must keep showing the fact associated with the run that actually produced today's numbers,
   never silently imply the run saw B.
2. A property has booking source A (recently imported) and booking source B (imported long ago).
   A run uses B. Oggi must represent B's own freshness, never the property-wide MAX across every
   booking source it happens to have.

This gate closes both with the smallest additive change: one nullable column, one typed domain
model, one repository method, one orchestration step, one new API field, one qualifying UI line.
**No CURRENT/STALE judgement, no threshold, no scheduler, no worker task.**

## Provenance vs. coverage

Coverage (`app.modules.decisions.coverage`, Gate 22) answers "which of the four user-facing
domains did this run attempt". Provenance (`app.modules.decisions.provenance`, this gate) answers
a different question: "from which input/source freshness did this run's facts derive". The two
are orthogonal and never share a JSON column - `analysis_coverage` and `input_provenance` are two
separate nullable `decision_runs` columns, each with its own typed model and its own serializer.

V1 is BOOKINGS only (the gate's own P0 scope) - no cost/labor provenance exists yet (P1,
deferred).

## The exact fact recorded

**"The latest SUCCEEDED import known, at analysis time, for the EXACT booking data source this
run used."** Nothing more is claimed. In particular, this is NOT "the file this run's numbers came
from" - canonical booking state is cumulative/upserted across many imports, so no single import
is "the" source of a run's facts. The UI reflects this precision: the user-facing copy is "Ultimo
import prenotazioni: ..." (a plain fact about when NINFA finished an import), never "Prenotazioni
aggiornate al ..." (which would claim the file's content was current through some business date -
`ImportJob.finished_at` proves nothing of the kind).

## Domain model

`app/modules/decisions/provenance.py`:

```
RunInputProvenance
    bookings: BookingProvenance
        data_source_id: UUID
        import_job_id: UUID | None
        last_successful_import_finished_at: datetime | None
```

`import_job_id`/`last_successful_import_finished_at` are both set or both `None` together
(enforced in `__post_init__`): the source identity can be known while its freshness fact is
UNKNOWN (no SUCCEEDED import exists yet for it), but a known import without a known timestamp -
or vice versa - is never a valid state. A timestamp is always timezone-aware and is canonicalised
to UTC on serialisation (`astimezone(UTC).isoformat()`), so the fingerprint (below) never depends
on which offset the DB/session session happened to hand back.

Versioned (`version: 1`) and strongly typed, exactly like `AnalysisCoverage`: `to_json()`/
`from_json()` are the only (de)serializers, an unsupported version raises `ValueError`, nothing
else in the codebase builds or reads this shape by hand.

## Persistence

One nullable JSONB column, `decision_runs.input_provenance` (migration `0012_input_provenance`,
additive, `decision_runs` stays append-only - the existing `decisions_forbid_update` trigger from
`0009_decision_layer` is untouched). Same `JSONB(none_as_null=True)` requirement as
`analysis_coverage` (Gate 22's own hard-won lesson: a nullable JSONB column binds a Python `None`
as the JSON literal `'null'`, not SQL `NULL`, unless declared this way - see
`docs/architecture/analysis-coverage-v1.md`).

**NULL means "not recorded", never "no booking source", never a fabricated historical
timestamp.** Every run persisted before this gate reads back as NULL; no backfill exists or is
attempted. `DecisionService.sync()`'s new `provenance` parameter defaults to `None` for exactly
this reason - every pre-Gate-23B caller (the whole existing test suite included, Gate-22-aware or
not) is unaffected and keeps persisting NULL.

## Import repository

`ImportJobRepository.latest_succeeded_for_data_source(data_source_id)` (Gate 23B's one new
repository method): the latest `SUCCEEDED` `ImportJob` of this EXACT data source, ordered by
`finished_at DESC` (never `created_at` - that only proves when the row was queued, not when the
import actually finished), `id DESC` as a deterministic tie-break. Workspace-scoped like every
other method on this repository. Never a property-wide/domain-wide `MAX` across every data source
- a property with several BOOKINGS sources gets the freshness of the ONE source a run actually
used.

## Orchestration

`app/cli/analysis.py::run_analysis` resolves provenance itself, right before calling
`DecisionService.sync()`: it already knows `booking_data_source_id` (the one it was given), looks
up `latest_succeeded_for_data_source` for exactly that id, and builds a `RunInputProvenance` -
`import_job_id`/`last_successful_import_finished_at` both `None` when no successful import exists
yet (a legitimate, non-fatal cold-start outcome, never a crash manufactured solely to produce a
timestamp). Gate 21's fail-loud guarantee is untouched: if any step before this one raises,
`DecisionService.sync()` is never reached, so no run (and no provenance) is ever persisted for a
partially-evaluated analysis.

## Replay / fingerprint semantics

Audited first (per the gate's own requirement), then folded into `run_input_fingerprint()` the
same way Gate 22's `coverage` parameter already is: an optional `provenance` parameter, omitted
entirely (not even as a null placeholder) when the caller passes none, so every pre-Gate-23B
fingerprint - Gate-22-aware or not - is byte-for-byte unchanged. Guaranteed behaviour, proven
directly in `test_decision_provenance_persistence.py`:

- same evaluations + same scope + same provenance -> idempotent replay (same `decision_run_id`).
- same evaluations + same scope + a NEWER successful import for the same source -> a genuinely
  distinct `DecisionRun`, so Oggi can show the new frozen timestamp. Proven both ways: the new run
  gets the new fact, and the OLDER run - already persisted - keeps reporting its own original
  frozen provenance forever afterward (a later import can never rewrite history).
- identical `(source id, import job id, finished_at)` repeated -> still an idempotent replay,
  never a spurious duplicate run.
- a DIFFERENT `booking_data_source_id`, otherwise identical evaluation content -> a distinct run.

## API contract

`DecisionFeedResponse` gains one additive field, `input_freshness`, always present and never null:

```json
{
  "input_freshness": {
    "bookings": {
      "status": "KNOWN",
      "last_successful_import_finished_at": "2026-09-29T09:15:00Z"
    }
  }
}
```

`status` is `"KNOWN"` or `"UNKNOWN"` - `"UNKNOWN"` covers BOTH "no provenance recorded at all"
(no run, or a run predating this gate) AND "a booking source was known but no SUCCEEDED import of
it existed yet at analysis time". A client never needs to distinguish the two: both mean the same
thing to a reader - no factual freshness timestamp to show. The internal `ImportJob`/`DataSource`
UUIDs the persisted provenance carries are deliberately never exposed (no frontend need for them
exists) - the public contract is narrower than the internal one, on purpose, exactly like
`analysis_coverage`'s own precedent.

## Oggi UI

Additive only - no new page, card or section, no CURRENT/STALE badge, no warning colour based on
age. `feed-state-view.tsx` adds one subordinate line (`.feed-state__freshness`) under
`ACTION_REQUIRED`, `DATA_QUALITY_LIMITED` and `NO_ACTION_REQUIRED` (never under `NOT_PROCESSED`,
which stays unchanged) - a SEPARATE line from Gate 22's own `.feed-state__coverage`, the two
render together without either one changing the other's copy:

- `KNOWN`: "Ultimo import prenotazioni: 29 settembre alle ore 09:15." - Italian long-form
  date/time formatting via `Intl.DateTimeFormat("it-IT", ...)`, extended by this gate with
  `formatPropertyLocalDateTimeItalian` in `lib/date/property-date.ts`, in the PROPERTY's own
  timezone (never the browser's).
- `UNKNOWN`: "Informazione sull'ultimo import prenotazioni non disponibile per questo run." - a
  neutral, factual statement, never alarming.

## Historical runs & NOT_PROCESSED

A run persisted before this gate (`input_provenance IS NULL`) reads back as `UNKNOWN` through the
API and renders the neutral unavailable line - never a crash, never a guessed historical import,
never a live query attempting to reconstruct what the run "must have" seen. `NOT_PROCESSED` (no
run at all) is left completely unchanged: no "last successful analysis date" is added here (P1,
deferred).

## Explicitly deferred (unchanged from Gate 21A/22A, plus this gate's own new ones)

Last successful analysis date when today is `NOT_PROCESSED`, a CSV optional-header typo warning,
cost freshness, labor freshness, CURRENT/STALE judgements and any freshness threshold, a
scheduler, a worker analysis task, Ask NINFA freshness context, a data-health dashboard.
