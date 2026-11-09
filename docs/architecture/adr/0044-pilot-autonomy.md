# ADR 0044: A pilot hotel runs without AGRIA: its rooms, its daily analysis, its channels, its own corrections

Status: accepted (Pilot Autonomy Gate). No migration, no new dependency. Amends
[automatic-analysis-policy-v1.md](../automatic-analysis-policy-v1.md) (Gate 26B),
[struttura-ui-v1.md](../struttura-ui-v1.md), [ota-dependency-v1.md](../ota-dependency-v1.md) and the
consequences of [ADR 0043](0043-dati-cause-and-denominator.md).

## Context

A product review found four things that still needed AGRIA's command line or a person's help:

1. "Configura inventario" reached the right block and did nothing there. The number of rooms could only be set with
   `python -m app.cli.pilot set-room-inventory`.
2. The daily analysis needed an external scheduler, a CLI opt-in per property and an import that same morning. Without an
   analysis for the day, Dati says nothing about occupancy, revenue or OTA.
3. "Telefono / Email" was not in Gate 9's closed dictionary, so it was unclassified. Product decision: it is direct, because
   the booking reaches the hotel with no intermediary.
4. A wrong answer NINFA remembered could not be corrected. On the demo, the file's status "Modificata" was answered "Non
   presentato", and every later file would have read it that way.

## Decision

### 1. The room inventory is one number, written on the nights the backend already reads

`RoomInventoryService` (`analysis/room_inventory.py`) behind `GET` and `PUT /properties/{id}/room-inventory`. There is no
second model: `room_inventory_daily` is what the observations, the detectors and the CLI already use.

- The person says "24 camere". It is written on every night from the property-local today on.
- No night already gone is touched, and no stored observation: it copied the capacity when it was taken, and a run keeps
  pointing at what it read. A change counts from today.
- The nights are written **ten years** ahead in one statement (3653 rows). **Refused:** a rolling window kept up by a job. A
  job that stops would make the capacity run out silently, and a rolling job could not tell a number a person said from a
  finite period an operator set with the CLI, without a new table. The far end is ten years away, and every save moves it.
- A number from 1 to 5000, whole. The limits are the backend's, and the form reads them from `GET`. 0 is a real value of one
  night (closed), not a capacity of a hotel. A capacity is still never inferred from the bookings.
- Nights set per period by an operator read as `varies`, with the first night's number, never a mean. Saving says it will
  apply one number to all of them. **No calendar editor in this gate**: a seasonal hotel with variable rooms still needs the
  CLI.
- A save that changed something asks for the same refresh an import asks for (`enqueue_refresh`). The refresh takes the
  day's next revision, so the occupancy follows the same day. A refresh that cannot be queued is logged and does not undo the
  save: the day's analysis takes the number in anyway. The same number again changes nothing and asks for nothing.

### 2. The day's analysis is the worker's own

`worker/daily.py`: a Procrastinate periodic task, every 5 minutes. Gate 26B refused periodic tasks because a once-a-day tick
missed for more than ten minutes is silently dropped. This one cannot lose anything that way: **being due is worked out each
time from what is stored**, never from when the tick last ran.

| Rule | Now | Before (Gate 26B) |
|---|---|---|
| Who asks | the worker, by itself | an external scheduler |
| Who is in | every property with exactly one active booking source and a successful import, enrolled by the tick. A policy switched off stays off | opt-in by AGRIA, with a CLI |
| When | from 10:00 on the property's own clock, once per local day | 10:00, by the scheduler |
| With no import that morning | it runs on the bookings NINFA holds | skipped (`NO_TODAY_BOOKING_IMPORT`) |
| What it analyses | what a refresh analyses (`scope.analysis_request`): labor and costs where they really are | Revenue and Distribution only |
| A job that fails | asked again at most 3 times a day, 1 hour apart | never |
| A job a dead worker left `doing` | put back by a later tick, at most 3 times | stayed there for ever, and its lock held back that property's analyses |

10:00 is the hour Gate 26B fixed: it is a constant (`DAILY_ANALYSIS_LOCAL_TIME`), not a setting per property.

**Why the import rule could go.** Gate 26B skipped because an observation was immutable per day, so a run on yesterday's
bookings could not be corrected that day. Same-day revisions lifted that: a file arriving later is the day's next revision.

**Why the domains widened.** A refresh looks at labor and costs. If the daily run did not, every day with no import would say
"Non analizzati: Costi, Personale", about data the property holds and the refresh before it had looked at.

**Idempotency.** A tick is unique per moment in the queue's own table, however many workers. A job carries a `queueing_lock`,
so one waits per property, and the same `lock` as a refresh, so one analysis of a property runs at a time. The policy task
evaluates again when it runs, and a run for today means skip. A page follows the day's job as it follows a refresh
(`latest_refresh` reads both).

**`dispatch-analysis` and `scripts/run-daily-analysis.sh` stay**, as an operator's catch-up at any hour. They do not enrol and
do not check the hour. No timer is shipped, because none is needed.

Finished ticks older than a day are removed by the tick itself: 288 a day would otherwise add about 100 000 rows a year.

### 3. What reaches the hotel itself is direct

`DIRECT_NORMALIZED_NAMES` gains the hotel's site (`website`, `sito`, `sito web`, `sito ufficiale`), the telephone and the
e-mail, alone or together (`telefono / email`, `phone / email`, ...), and `walkin`. The match stays exact, on the normalised
label: `Telefono Booking`, `Web` and `Booking Engine` stay unclassified, and a verified channel type still wins. The rules
version stays `ota-dependency-v1`: the formula and the thresholds did not move, and the fingerprint of an evaluation already
changes when a channel's group does.

### 4. No verdict is two different things to read

`DistributionOverview.insufficiency` is `HISTORY` when the only reason is `OTA_COMPARABLE_SAMPLE_INSUFFICIENT`, else
`DATA_QUALITY`. With `HISTORY` it also carries the periods it has and needs (`comparable_periods_available`, `_required`).
The page says "Storico ancora insufficiente", with the current share and "Periodi confrontabili disponibili: 0 su 5", and
asks for nothing. With `DATA_QUALITY` it says what to look at, as ADR 0043 decided. The minimum of 5 is not touched.

### 5. What a source remembers can be corrected by the person

`data_sources/remembered_answers.py`, in "Gestisci" under "Risposte ricordate": `GET`, `PUT` and `DELETE`
`.../data-sources/{id}/remembered-answers[/{answer_id}]`. Two things are shown, because two things are remembered:

- **Words** ("Stato «modificata» → Non presentato"): `status_mapping`, `role_mapping`, `category_mapping`, `channel_mapping`.
  A word belongs to the **source**, not to a family: that is where the import keeps it. It can be corrected within the list its
  own question offers, or forgotten. Forgotten, a word the engine does not know is asked about again; one it knows goes back
  to the engine's meaning. A channel word can only be forgotten: nobody is asked about one.
- **Kinds of file** (a `source_learning.Memory` a person taught, or said what it holds): shown by their columns, with the
  formats and the scope remembered. A family can only be forgotten, whole and alone: the next such file is read like one
  nobody taught, and the other families do not change.

**Refused:** forgetting one scalar answer of a family (the date order, say). A family recognised by its saved matching reads
the formats from the profile, so the question would not come back, and the page would have lied. The matching of the columns
has its own way ("Modifica associazioni", "Dimentica configurazione").

**Nothing is retroactive.** Only the profile changes, and no analysis is asked for. The note on the page says what to do if the
data already imported are to change too: bring the file again. No word changes meaning by itself, and nothing in the code knows
"Modificata". A correction takes the lock imports take, so neither overwrites the other.

**Audit.** A short trail in `format_options.learning.corrections` (the last 20: when, what, from what to what, who), next to what it
changed, plus a structured log line. The row says which source, property and workspace. It survives later imports, and goes
with the profile if "Dimentica configurazione" removes it.

## Consequences

- **A daily run on bookings that did not arrive looks like bookings that did not come.** NINFA has no notion of how old the bookings
  are, and the observation of a day with no import says nothing was picked up. `REV_PICKUP_LOW` reads that the way it reads a real
  absence of bookings once there is enough history (five weeks), and that observation joins the history of later days. A hotel
  that imports every few days can see a false alarm that clears at the next file. The page shows the fact ("Ultimo import
  prenotazioni: ..."), and no detector was changed. Until bookings arrive by themselves this is the known cost of a run every day,
  and it needs a product decision.
- A property's first run is at its first import or at 10:00, whichever comes first. A day with the worker down all day has no run,
  and is not recovered: an observation cannot be dated in the past.
- The worker must be running. It is supervised (`deploy/systemd/ninfa-worker.service`), and it is the one thing the daily analysis
  now depends on.
- `app.modules.analysis.policy.AutomaticSkipReason.NO_TODAY_BOOKING_IMPORT` is gone: `NO_BOOKING_IMPORT` means the source has
  never delivered.
- The API gains fields and routes only.
