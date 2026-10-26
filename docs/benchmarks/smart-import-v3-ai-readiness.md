# Smart Import V3 - AI readiness benchmark

Run 2026-10-26 on branch `feature/smart-import-v3-ai-readiness` (base `main` 1479a8d). The model is a stand-in (an oracle, models that are wrong, models that fail); nothing leaves the process and no vendor is involved.

> **Scope.** FIRST SCREEN ONLY: each document is understood once, as a person's first upload, and scored against the truth WITHOUT the conversation rounds. P0/P1 and the other counts here are NOT comparable with the official full-flow benchmark (docs/benchmarks/smart-import-v3-question-reduction-1.md), which also plays the answers a careful person gives. What this benchmark compares is each mode against the SAME run with no model.

## What was run

* **corpus** - the 240 documents of the Smart Import benchmark (hash unchanged).
* **variants** - 148 documents the rules read completely, each with one decisive column whose header was replaced by an opaque label, so that the model is actually asked. Same files, same truth, except that the file may not be automatic any more.

## Safety with a model that is wrong, sure of it, obedient or broken

AI-caused = compared with the run with no model. Newly automatic and made READY must be 0.

| model | population | asked | screens changed | newly automatic | made READY | AI-caused false automation | AI-caused P0 | AI-caused P1 | PII browser | PII to model |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| plausible_wrong | corpus | 24 | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| wrong | corpus | 24 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sure_and_wrong | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| obeys_injection | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| says_another_kind | corpus | 24 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| agrees | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| malformed | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| not_json | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nothing | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| unsupported_field | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| heavy_answer | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| timeout | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| http_429 | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| http_500 | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| raw_exception | corpus | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| plausible_wrong | variants | 49 | 8 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| wrong | variants | 49 | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| sure_and_wrong | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| obeys_injection | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| says_another_kind | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| agrees | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| malformed | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| not_json | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nothing | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| unsupported_field | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| heavy_answer | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| timeout | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| http_429 | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| http_500 | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| raw_exception | variants | 49 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## A wrong model: what it changes and what protects the file

| model | population | proposed | accepted (MEDIUM) | discarded | MANUAL to ASK | BLOCKED to ASK | questions added or precompiled |
|---|---|---:|---:|---:|---:|---:|---:|
| plausible_wrong | corpus | 71 | 36 | 35 | 0 | 0 | +6 |
| wrong | corpus | 100 | 25 | 75 | 0 | 0 | +6 |
| sure_and_wrong | corpus | 200 | 0 | 200 | 0 | 0 | +0 |
| obeys_injection | corpus | 202 | 0 | 202 | 0 | 0 | +0 |
| plausible_wrong | variants | 62 | 8 | 54 | 1 | 1 | +2 |
| wrong | variants | 64 | 2 | 62 | 2 | 0 | +2 |
| sure_and_wrong | variants | 128 | 0 | 128 | 0 | 0 | +0 |
| obeys_injection | variants | 128 | 0 | 128 | 0 | 0 | +0 |

## Cost and egress (the model is asked about the files with something open)

| population | asked | calls/file mean | p95 | max | payload mean | p50 | p95 | max | hard limit | blocked | false-positive blocks | actual PII leaks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| corpus | 24 of 240 | 0.1 | 1 | 1 | 1862 | 1704 | 2513 | 3387 | 6000 | 0 | 0 | 0 |
| variants | 49 of 148 | 0.331 | 1 | 1 | 2007 | 1953 | 2353 | 2575 | 6000 | 0 | 0 | 0 |

## What a perfect model would be worth

| population | asked | really improved | questions precompiled | suggestions at MEDIUM | MANUAL to ASK | BLOCKED to ASK | ASK with a confirmation | new automatic |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| corpus | 24 | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| variants | 49 | 49 | 50 | 49 | 45 | 1 | 3 | 0 |

## The 21 questions that remain on the corpus

By class: {'UNSUPPORTED': 3, 'DETERMINISTIC_REQUIRED': 6, 'HUMAN_REQUIRED': 9, 'AI_HELPFUL': 3}. A perfect model could remove **0** of them today.

| document | question | class | why |
|---|---|---|---|
| L36_abbreviations_known | VALUE_LABELS F&B, FO, HK, HSKP, REC | UNSUPPORTED | Hotel jargon a model reads - but the closed answer has no 'meaning of a label'; a lexicon would also do it. Codes stay asked by product decision. |
| L62_neg_swapped_header_labels | DEPARTMENT_ROWS | DETERMINISTIC_REQUIRED | The headers contradict the values: a contradiction is the rules' to detect, never a model's to smooth over. |
| LO07_department_in_a_label_value_block | DEPARTMENT_ROWS | DETERMINISTIC_REQUIRED | 'Reparto: X' above the table is structure the parser should read; no model needed. |
| LO15_abbreviated_department_header_and_codes | VALUE_LABELS FO, HK, REC | UNSUPPORTED | As L36: a label-meaning capability, or a lexicon. Codes stay asked by product decision. |
| B14_booker_and_guest_names_two_columns | COLUMN_MEANING Price | HUMAN_REQUIRED | Which amount 'Price' is, is not in the file; money is never guessed (product decision). |
| B41_office_channel_manager_extract | COLUMN_MEANING Total | HUMAN_REQUIRED | A bare 'Total': room revenue or the whole stay? Approved to stay MEDIUM + confirm. |
| B42_office_front_desk_monthly_report | COLUMN_MEANING Ricavo | HUMAN_REQUIRED | Which revenue is not in the file; money is never guessed. |
| B50_neg_arrival_and_departure_swapped | DATES_REVERSED Arrivo | DETERMINISTIC_REQUIRED | Every arrival after its departure: a value check, and a person decides. |
| B51_neg_occupancy_calendar_not_bookings | DOMAIN | DETERMINISTIC_REQUIRED | A room-by-day calendar is not bookings: the kind of data is the rules' call. |
| B55_neg_checkout_before_arrival_rows | DATES_REVERSED Arrivo | DETERMINISTIC_REQUIRED | Departures before arrivals: a value check. |
| B64_adv_near_identical_date_headers | COLUMN_MEANING Check-in | HUMAN_REQUIRED | Planned and actual check-in side by side: two candidates for one field. |
| B64_adv_near_identical_date_headers | COLUMN_MEANING Check-in effettivo | HUMAN_REQUIRED | Same file: the choice between the two is the hotel's. |
| BO01_channel_written_as_codes | COLUMN_MEANING Imp. | HUMAN_REQUIRED | An abbreviated amount: which one is not in the file. |
| BO03_channel_manager_abbreviations | COLUMN_MEANING Tot | HUMAN_REQUIRED | An abbreviated total: which one is not in the file. |
| BO09_status_written_as_ok_canc_ns | VALUE_LABELS OK, CANC, NS | UNSUPPORTED | Status codes: a label-meaning capability or a lexicon. |
| BO09_status_written_as_ok_canc_ns | COLUMN_MEANING Stato | AI_HELPFUL | The rules already propose 'status' (MEDIUM): a model would only agree, and agreeing cannot lift MEDIUM. |
| C33_credit_notes_negative_amounts | COLUMN_MEANING Imponibile | HUMAN_REQUIRED | Negative amounts: credit note or error - the hotel's convention. |
| C38_several_lines_per_invoice | COLUMN_MEANING N. documento | DETERMINISTIC_REQUIRED | The same number on several lines is how invoices are written: a rule, not a model. |
| C44_office_accounting_export_header_on_row_five | COLUMN_MEANING Data reg. | HUMAN_REQUIRED | Registration date or invoice date: an accounting convention not in the file. |
| C46_office_manual_expense_sheet | COLUMN_MEANING Da chi | AI_HELPFUL | Informal wording ('from whom'): exactly what a model reads - but the rules already propose it at MEDIUM. |
| C46_office_manual_expense_sheet | COLUMN_MEANING Cosa | AI_HELPFUL | Informal wording ('what'): as above. |
