# 0038 — The import asks for the analysis, and the queue says how it went

## Context

An import left the Home on "Analisi non ancora disponibile" until an operator or an external scheduler
ran the analysis. Gates 25-26 had deliberately made NINFA schedule nothing and trigger nothing on import.
The pilot's flow needs the opposite for the person using the page: bring a file, see the result.

Three things constrained the answer: the API package does not depend on Procrastinate; `OBSERVED` snapshots
are immutable per day; and the feed's four states must keep their meaning.

## Decisions

1. **A successful import made through the web API queues one job** after it has committed. The operator's
   import commands still trigger nothing, and the automatic policy (Gate 26B) is unchanged.
2. **The API writes the row itself** in `procrastinate_jobs` (`analysis/queue.py`), the same `INSERT` as
   `procrastinate_defer_jobs_v1`, on a schema this repository vendors. No new dependency for the API.
3. **What to analyse is decided when the job runs** (`analysis/refresh.py`): only the choices an operator
   would make by hand, from what is really stored. No detector logic.
4. ~~**A day keeps its first observation.**~~ Superseded by [ADR 0039](0039-same-day-revisions.md): a changed
   night is the day's next revision, analysed at once. What is left is a stored reconstruction on today's key: the
   job queues itself for the next local day, never forced and never reported as a failure.
5. **The state is read, not recorded**: `analysis/status.py` derives it from imports, runs and the queue's
   own tables. No table, so nothing can disagree; and a descriptor beside the feed, so `FeedState` is not
   deformed.

## Consequences

- The worker must be running for an import to reach the Home; when it is not, the status says so after
  5 minutes (`DELAYED`), and the imported data are not affected.
- The API is coupled to the vendored queue schema in one module. A Procrastinate upgrade that changes it
  already needs a migration here, and `test_analysis_refresh.py` runs against the real table.
- ~~A second file that changes bookings on the same day updates the data at once and the analysis the next
  day.~~ ADR 0039 made it the same day.
- A run may now evaluate several cost months (`AnalysisRunRequest.cost_periods`) and only the labor dates a
  source covers (`labor_work_dates`). `cost_year` / `cost_month` keep working for the operator commands.

See [post-import-analysis-v1.md](../post-import-analysis-v1.md).
