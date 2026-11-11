# NINFA — Post-import analysis V1 (an import brings the analysis up to date by itself)

```
FILE -> understanding -> validation -> import -> server-side dispatch -> worker -> analysis services
     -> decision sync -> Home / Dati
```

The same job follows a room inventory saved ([ADR 0044](adr/0044-pilot-autonomy.md)), and a page follows the day's own analysis the same
way ([automatic-analysis-policy-v1.md](automatic-analysis-policy-v1.md)).

The person brings a file; nobody starts an analysis. **No migration and no new dependency.** The
detectors, the priority ranking and the decision sync are untouched: this is orchestration, and every
number is still computed by the engines (`analysis.service.run_property_analysis`).

| | |
|---|---|
| `analysis/queue.py` | the API's one door to the worker: a row in `procrastinate_jobs`, whose schema this repository vendors (revision 0002). The API does not depend on Procrastinate |
| `analysis/refresh.py` | what to analyse, decided **when the job runs**, from what is really stored |
| `analysis/status.py` | where the analysis stands against the data: a descriptor beside the feed |
| `worker.tasks.refresh_property_task` | `analysis.refresh_property`, the job itself |
| `DataSourcesService.import_file` | the dispatch, after a successful import |

The dispatch happens after the import has committed and cannot undo it: a request that cannot be
queued is logged, the data stay imported, and the status says `NEW_DATA` and offers to ask again. The
operator's own import commands trigger nothing, as before.

One job waits at most per property (`queueing_lock`), and one runs at a time (`lock`). A job carries
only the property's identity, so a job that waited still analyses what is there by then.

## What a refresh analyses

| Kind of data | What is analysed | What is never done |
|---|---|---|
| Bookings | the property's ONE active source with a successful import, the same 30 nights from the local today as the automatic analysis | choosing between several sources (`SEVERAL_SOURCES`) |
| Labor | the ONE active source, on the work dates of that window it really has entries for | evaluating a date the file says nothing about |
| Costs | the concluded months the invoices touch, however many a file spans (the newest 12 at most) | assuming the current month: the month in progress is never a cost of the month |

**Every engine needs bookings**: their targets and their denominators are its snapshots. With no
bookings nothing runs, and the status says what the property holds and what it lacks
(`NEEDS_BOOKINGS`). Labor and costs are still shown in Dati, which reads them directly.

## Several files on one day

A second file that changes something is analysed the same day, whatever it holds: a changed night joins
the day as its next revision, and nothing earlier is rewritten ([same-day-revisions-v1.md](same-day-revisions-v1.md)).
A file that changes nothing queues nothing, moves no status and no provenance.

`DEFERRED` is what is left of the old rule: a stored reconstruction on today's key, which only a change of the
property's time zone can produce. It clears by itself on the next local day, so it is not called a failure:

- the job ends normally and the refresh is queued for just after the next local midnight;
- the status says `DEFERRED`, with `next_attempt_at`;
- a new import brings a waiting job forward, instead of leaving its data behind it.

## The status

`GET /api/v1/properties/{id}/analysis/status`. `FeedState`, coverage and freshness keep their meaning;
this says what they cannot, from three facts already stored (`import_jobs`, `decision_runs`, the queue's
own tables). Nothing is recorded for it, so nothing can disagree with them.

| State | Meaning | What the page says |
|---|---|---|
| `NO_DATA` | nothing imported | the old message, and the way to the first file |
| `NEEDS_BOOKINGS` | data, but no bookings | what it holds and what it lacks |
| `SEVERAL_SOURCES` | several booking sources | it does not choose |
| `NEW_DATA` | imports that changed data since the analysis, nothing under way | can be asked for (`can_retry`) |
| `IN_PROGRESS` | a job is waiting or running | "Aggiornamento analisi…", and it re-reads by itself |
| `DELAYED` | the same, for more than 5 minutes (a stopped worker) | it takes longer than usual: neither "in progress" for ever nor a failure |
| `DEFERRED` | see above | the new data count from tomorrow |
| `FAILED` | the job failed | the data are safe, and the analysis did not update; can be asked again (`can_retry`) |
| `UP_TO_DATE` | the analysis has seen every import that changed something | "Analisi aggiornata." right after an import, nothing at rest |

`POST .../analysis/refresh` is only the recovery: it queues a job in `NEW_DATA` and `FAILED`, and changes
nothing in any other state.

A page asks again every 3 seconds **only while a refresh is under way**, and re-reads its own data when
one ends. The API responses are `no-store` and the browser keeps no cache of them: a page that opens
reads the latest. There is no client query cache to invalidate.

## Decisions to confirm

1. **Revenue for labor is on-books**, the only revenue NINFA holds for days to come (`data-ui-v1.md`).

The two others this document used to list, a second bookings file waiting for the next day and a second
staff file refused, were lifted by [same-day-revisions-v1.md](same-day-revisions-v1.md).

See [ADR 0038](adr/0038-post-import-analysis-refresh.md).
