# ADR 0041: A memory takes nothing away by itself

Status: accepted (Remembered Scope Safety V1.2.2). Migration `0016_remembered_scope`.

## Context

[ADR 0040](0040-import-scope-semantics.md) remembers per family of files whether they hold everything of their period, and
named the consequence: a family has one answer. The same source can export a part of its period with identical columns. With
`FULL` remembered, that file would mark what it lacks as gone, with no question, and a count on the summary as the only
warning. A count can be missed. Taking data out of what counts should not depend on someone reading a line.

## Decision

1. **A remembered `FULL` removes nothing on its own.** If it would really stop something counting, and nobody has said what
   the file is on this import, a person is asked. With nothing to lose, nobody is.
2. **The answer is about this import.** "No, it is a part" does not make the source partial: one export says nothing about the
   next. The memory changes only with an explicit word (`remember_scope`, a box that starts empty; the first answer about a
   structure says on screen that it will be remembered, and sends it).
3. **A wrong memory can be corrected where it shows.** A remembered part asks nothing, so the summary says what stays and
   offers the same two answers behind a quiet action. No settings page.
4. **The server computes everything, and computes it again.** Reading: `ScopePreflight`. Before the commit: the file is read
   again and the decision compared, so a figure that moved refuses it. Under the source's lock: the removals are counted
   once more against what the person saw, and if they differ nothing is imported. A browser's number never decides anything.
5. **The job says why.** `file_scope` is what was applied; `remembered_file_scope` is what the memory held then. A memory
   moves on, so it cannot say this later: that is why this needs a column and a migration.
6. **The same bytes are not asked about twice** if they were said to be a part. Never if they were complete: that a file took
   something away once is no reason to take anything away now.

## Reading a removal back

| Remembered | Applied | With removals |
|---|---|---|
| none | `FULL` | the first answer about this structure |
| `FULL` | `FULL` | a person confirmed it on this import |
| `PARTIAL` or `DELTA` | `FULL` | a person said this one holds everything |
| `FULL` | `PARTIAL` | none: this import was declared a part |

## Why not the alternatives

- *Ask on every file:* friction on every normal day, and people stop reading a question they always answer the same way.
- *Keep the count on the summary as the only warning:* what this gate exists to replace.
- *Infer a partial file from how much it lacks:* a threshold is a guess, and a guess here is silent. Same reasoning as ADR 0040.
- *Let "No" change the memory:* one partial export would stop a source's complete files from ever taking anything away, with
  no sign of it.
- *Put the remembered scope in the family's JSON:* it would need writing on imports that save nothing, and it is capped and
  dropped with the configuration. A job is where an import's facts live.
- *Trust the figure shown at the commit:* the data may have moved. *Recompute and apply a different figure silently:* the
  person agreed to another one. So a figure that moved refuses, and the file is read again.

## Consequences

- Every decision carries `remembered_file_scope` and `expected_removals`, verified with the rest. Posted back different, they
  only get it refused.
- A file refused for this reason is a failed job with `IMPORT_PLAN_CHANGED`, and nothing of it is imported.
- A department missing on a day the file names, when the file names that department elsewhere, is not this rule's: it is the
  replacement rule of ADR 0039, the same under any answer, and it asks nothing. Pinned by a test.
- The downgrade of `0016_remembered_scope` refuses once a job holds the column.

See [import-scope-semantics-v1.md](../import-scope-semantics-v1.md).
