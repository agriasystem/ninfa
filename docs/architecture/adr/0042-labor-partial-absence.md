# ADR 0042: In a staff file that is not complete, a missing (day, department) means nothing

Status: accepted (Pilot Safety Final Fix). No migration. Amends decision 4 of
[ADR 0039](0039-same-day-revisions.md) and removes the exception recorded in [ADR 0041](0041-remembered-scope-safety.md).

## Context

ADR 0039 let a staff file speak "for the work dates it names and the categories it names, together". So a file holding
Monday (for Reception) and Housekeeping (on Tuesday) emptied Housekeeping on Monday. That happened under any scope,
`PARTIAL` and `DELTA` included, through the CLI too, with no question, and with `removal_count` 0, because the reading with
no scope already cleared the cell, and the count is the difference between that reading and a complete one. A person
was never told.

That a day is in the file, and that a department is in the file elsewhere, does not show that the pair was removed on
purpose. A file of the shifts that changed, or of one manager's departments, has exactly that shape.

## Decision

1. **A file speaks for the cells it holds**: each (work date, category) it has a row for. The days of a file times its
   categories are never read as what it speaks for.
2. **Only a file a person said is complete (`FULL`) takes anything away**, on every day from its first to its last row,
   as ADR 0040 and 0041 already say, with the same question, count, confirmation, lock check and history.
3. **`PARTIAL`, `DELTA` and a file nobody said anything about** update the cells they hold and remove none.
4. **Zero hours is not a removal.** A row of 0 hours is accepted today and means a plan of zero hours: the detector reads it
   as a department scheduled for nothing (`build_target_plan`), not as one with no plan. Its meaning is not changed here.
   To take a cell out of what counts, a person imports the plan as complete.
5. Planned and worked hours stay read apart, each by this rule; same-day revisions and the no-op are unchanged.

## Consequences

- A missing cell now counts as an absence like any other: a complete file reports it in `removal_count`, so a remembered
  `FULL` asks first (`FILE_SCOPE_CONFIRM`) and a first answer is asked for (`FILE_SCOPE`). Before, these cells were cleared
  and not counted.
- A part that only repeats what already counts, minus some cells, is now a no-op: it changes nothing.
- The CLI imports never take anything away, for staff too.
- One rule, one place: `FileCoverage.clears` in `labor.current_plan`. Pinned by `test_labor_partial_absence.py` and the
  pure cases in `test_labor_current_plan.py`.

## Why not the alternatives

- *Keep the cross product for files nobody spoke about:* the same silent removal, through the CLI or a hand-built mapping.
- *Make 0 hours mean "remove":* it already means something to the detector; changing it would silently change history.
- *A delete marker column:* a new proprietary format for something a complete file already says.
