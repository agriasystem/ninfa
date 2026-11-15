# ADR 0051: An unread column that moves with a read one is never lost in silence

Status: accepted (Smart Import OpenAI Safety Closure). A defect of the RULES, found by the challenge benchmark of [ADR 0050](0050-the-semantic-layer-reads-names-ninfa-proves-values.md), closed in
the rules - not in any provider. No migration, no dependency, no change to FULL / PARTIAL / DELTA, to Source Learning, to the UI or to the Decision Engine.

## Context

The challenge benchmark replaced one header of 148 official, correct workbooks with a word the rules do not know, and measured what the RULES ALONE then do. In 41 of 290 files they offered the
file as READY and silently left a column out:

| Field of the unread column | Files |
|---|---:|
| `actual_hours` (the planned hours are read) | 32 |
| `planned_hours` (the actual hours are read) | 8 |
| `room_revenue` (the revenue of the whole stay is read) | 1 |

**Root cause.** An import can run with ONE of two measures of the same thing (planned OR actual hours; the room's revenue OR the stay's). The requirement is therefore met by the one that is read,
and nothing in the rules looks at what is left over: an unread column is "innocent" by default. When the unread column is in fact the other half - the actual hours of a roster whose planned hours
are read - its numbers silently never reach NINFA, and nothing on the screen says so. The bookings group has no alternative at all, so for revenue the protection did not even exist as a group.

It was found by a benchmark, not by a person; with the model off it is what every hotel on the pilot would have got.

## Decision

A new, deterministic, provider-free rule, in the shared understanding (`understanding_siblings.py`, called from `UnderstandingService`), that holds with the model OFF, in SHADOW or ASSIST against
any model, and with the original assistant:

* A kind of data declares its **siblings** (`DomainSem.siblings`): fields that measure the same thing in two ways - `planned_hours` / `actual_hours`, `planned_cost` / `actual_cost`,
  `room_revenue` / `total_revenue`.
* When ONE member of a pair is read and the other is not, every **free** column (read by nobody, not personal data, not left out on purpose, not already a question, at least nine tenths numbers,
  enough values) is compared with the read member **row by row**. If, on at least 90% of the rows that both have, the ratio is inside a band (0.6 to 1.7: wide enough for actual against planned
  hours, or a stay against its room; too narrow for a count of nights, a commission or a per-night price) and its values would be a valid reading of the missing member, the file is not READY.
* **A whole is never smaller than its part** (`DomainSem.parts`: the room's revenue is the part, the stay's total the whole). When the part is read, a column can only be the whole if it is not
  smaller than the part (a 2% rounding is the only slack): "Netto dopo commissione", 87% of the room, is not the stay's total and is left alone. This direction was added after the first version
  of the rule questioned two official adversarial files (`UB107`, `UB117`) that the benchmark had always read correctly.
* **...unless the read column's own name is also a name of the other half.** "Totale soggiorno" is read as the room's revenue (the rules weigh 0.90 against 0.88 for the stay's total), but it is
  as much a stay total: NINFA does not know which half it holds, so the direction does not apply and an unread column a little SMALLER ("Incasso", 91%) may be the room's real revenue. This is the
  one case (`B07`, challenge) that the direction alone let through; it is decided by the read column's name, found with the same `name_candidates` the reading itself uses, not by a word list.
* **Two things rule an unread column OUT, and only out.** (a) Its header NAMES another kind of the same measure: the labor vocabulary that already said "contract, overtime, holiday, break hours
  are another thing, left alone" (`DomainSem.other_kinds`, the existing `_OTHER_HOURS`) - "Ore da contratto" moves with the hours worked and is not the planned hours. The header never rules a
  column in. (b) Its numbers are the same as the read column's, row after row (within the 2% of a rounding), and the field is money: nothing the import lacks would be lost (found by an older
  test: a room number 101, 102... beside amounts 101.50, 102.50...). Hours are never exempted this way: an actual equal to the plan is still a different fact.
* **Hours** become a question the person answers like any other ("Is «Impegno reale» the actual hours?"; "No, I check the columns" opens the matching screen, whose saved profile ends the
  question for that shape). **Money** is never put as a yes or no (an earlier, approved decision): the file goes to the matching screen.
* **A held file stays held.** A file the rules send to the matching screen (money in competition, a kind of data nobody confirmed, an unread amount that moves with a read one) stays MANUAL
  only while no question is open: the level rule answers ASK as soon as ANY question exists. So a model's hint on an optional column (the new "every uncertain
  model-named column is a question" invariant, for every provider) is not turned into a question on a held file; it would have taken the person off the matching screen onto a yes/no one. The
  readiness benchmark found it (`CO04_vat_register_two_rates_two_dates`, plausible-wrong stand-in: MANUAL -> ASK, one AI-caused P1); the person sees every column on the matching screen anyway,
  and `main` kept that file MANUAL, which it does again.
* The header is never read - it is what NINFA could not read. No model is consulted, and a model that names the column does not lift the rule: hours are never certified by a model, so the question
  stays. A family the person already taught, with the same shape, is not asked again.

It is a rule about VALUES, not a list of header words, so it does not depend on the vocabulary, the language or the benchmark's synthetic data; it asks only about columns that behave like the other
half.

## What changes, measured

* Rules alone, challenge set: unsafe READY **41 -> 0** (READY 60 -> 19, ASK 76 -> 116, MANUAL 154 -> 155).
* Official benchmark (240), the layer off: **240 identical to `main`**. The first version of the rule moved ONE verdict, `L55_office_monthly_hours_report` (READY -> ASK: its "Ore da contratto"
  moves with "Ore lavorate"); the vocabulary exclusion above gives that file back with no change of any expected value. Universal Understanding V2 (417) and Source Learning answer identically too.
* Two older tests (`test_hours_of_another_kind_are_left_alone_without_a_question`, `test_a_column_with_the_number_of_the_room_is_not_a_count_of_rooms`) failed against the first version of the
  rule: they are the reason for the two exclusions, and neither was changed.

## Consequences

* A file can become ASK or MANUAL where it was READY: safety over automation.
* Seen in the benchmark, with the oracle stand-in: 12 challenge files whose optional `rooms` count is renamed (READY under the rules, which leave the unread count out: the V1.1 decision is "one room
  per row" when the column is absent) become a question when a model NAMES that column, because a count is never promoted by a model. The rules alone do not ask about an unread count; a model that
  names it makes it a question. That is the price of "a model's word alone never puts values in a field", and the benchmark's truth treats the unread optional count as safe (it is not critical).
* The rule is a candidate for the same treatment of other alternatives (the costs' net / gross); the benchmark found none, so none was added.
* The original Anthropic assistant is unchanged by this ADR; it benefits from the rule, which is not about it.
