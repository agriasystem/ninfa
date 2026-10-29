# NINFA Smart Import — Universal Understanding Benchmark V2 (BEFORE: the engine of fea4022)

Generated 2026-10-29. IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called.

Unseen documents, generated from recipes (none is in the official 240-document corpus), with the truth written next to each file and never read from Smart Import. First upload of each file: no learned profile.

## Corpus

- **402** documents: 360 positives (Prenotazioni 120, Personale 120, Costi 120), 27 negatives, 15 unsupported files.
- Difficulty of the positives: EASY 90, MEDIUM 120, HARD 90, ADVERSARIAL 60.
- 323 xlsx / 79 csv, 34 with several sheets, 126 with personal data, 42 distinct structures.
- sha256 `2a06f243f009c7ce066a6ff5b9fafaee54cc437ad32691d74a3a4b89a19e11bc`

## Targets

| Target | Wanted | Actual | Met |
|---|---|---|---|
| false automation | == 0 | 4 | **NO** |
| P0 findings | == 0 | 10 | **NO** |
| critical wrong mapping (committed) | == 0 | 3 | **NO** |
| necessary-question recall | >= 1.0 | 0.7353 | **NO** |
| safe fallback (negatives + unsupported) | >= 1.0 | 1 | yes |
| personal data leaked / not excluded | == 0 | 22 | **NO** |
| domain accuracy (strict) | >= 0.99 | 0.969 | **NO** |
| header accuracy (strict) | >= 0.99 | 0.9972 | yes |
| table accuracy (strict) | >= 0.99 | 0.9972 | yes |
| required precision | >= 0.995 | 0.9891 | **NO** |
| required precision, committed claims | >= 0.995 | 0.9961 | yes |
| required recall | >= 0.99 | 0.8254 | **NO** |

## Results by group (positive documents)

Domain / header / table are STRICT: a document the engine could not read counts as a miss. FA = false automation. Crit. wrong = a CERTAIN wrong reading of a fact a business decision rests on. Necessary Q = recall of the questions a person must be asked.

| Group | Docs | Domain | Header | Table | Req. prec. | Req. recall | Opt. prec. | FA | Crit. wrong (committed) | Zero-question | Necessary Q | Unneeded Q | PII | P0 | P1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| All positives | 360 | 96.9% | 99.7% | 99.7% | 98.91% | 82.5% | 98.7% | 4 | 3 | 22.6% | 73.5% | 139 | 13 | 10 | 309 |
| Prenotazioni | 120 | 95.8% | 99.2% | 99.2% | 98.50% | 77.8% | 100.0% | 0 | 3 | 8.8% | 62.5% | 13 | 1 | 2 | 210 |
| Personale | 120 | 94.9% | 100.0% | 100.0% | 99.73% | 84.9% | n/a | 4 | 0 | 40.9% | 81.2% | 76 | 12 | 8 | 21 |
| Costi | 120 | 100.0% | 100.0% | 100.0% | 98.75% | 86.5% | 96.8% | 0 | 0 | 19.6% | 70.0% | 50 | 0 | 0 | 78 |
| EASY | 90 | 95.6% | 100.0% | 100.0% | 100.00% | 81.1% | 100.0% | 1 | 0 | 24.4% | n/a | 32 | 0 | 1 | 80 |
| MEDIUM | 120 | 97.5% | 100.0% | 100.0% | 99.41% | 83.8% | 100.0% | 2 | 0 | 23.3% | n/a | 59 | 13 | 7 | 116 |
| HARD | 90 | 97.8% | 98.9% | 98.9% | 98.08% | 81.5% | 100.0% | 0 | 3 | 20.0% | 86.4% | 32 | 0 | 1 | 92 |
| ADVERSARIAL | 60 | 96.4% | 100.0% | 100.0% | 96.69% | 84.4% | 88.9% | 1 | 0 | 16.7% | 50.0% | 16 | 0 | 1 | 21 |

## Negatives and unsupported files

- Negative office documents (27): safe fallback 27/27, offered as automatic 0.
- Unsupported files (15): clean refusal 15/15.

Wrong readings of a critical fact at ANY level (a LOW guess the person is asked about counts too): 8; committed (certain and not asked): 3.

## Findings

| Severity | Findings | Documents (worst) |
|---|---|---|
| P0 | 10 | 10 |
| P1 | 309 | 146 |
| P2 | 231 | 115 |
| P3 | 2 | 0 |

| Category | Findings | Documents |
|---|---|---|
| DOMAIN_WRONG | 14 | 14 |
| HEADER_WRONG | 1 | 1 |
| TABLE_BOUNDARY_WRONG | 1 | 1 |
| FIELD_WRONG | 14 | 12 |
| FIELD_MISSED | 362 | 204 |
| PII_LEAK | 5 | 5 |
| QUESTION_MISSING | 8 | 8 |
| QUESTION_UNNECESSARY | 141 | 105 |
| FALSE_ZERO_QUESTION | 3 | 3 |
| UNSAFE_IMPORT | 1 | 1 |
| OTHER | 2 | 2 |

## By recipe

| Recipe | Docs | With findings | P0 | P1 | P2 |
|---|---|---|---|---|---|
| adv_ambiguous_date_order | 4 | 3 | 0 | 2 | 1 |
| adv_bank_statement | 2 | 0 | 0 | 0 | 0 |
| adv_bare_rate_next_to_hours | 2 | 2 | 0 | 0 | 2 |
| adv_bookings_under_costs_title | 1 | 1 | 0 | 0 | 1 |
| adv_bookings_under_staff_title | 2 | 0 | 0 | 0 | 0 |
| adv_country_as_source | 2 | 2 | 0 | 0 | 2 |
| adv_data_on_a_hidden_sheet | 4 | 0 | 0 | 0 | 0 |
| adv_decoy_columns | 2 | 1 | 0 | 1 | 0 |
| adv_department_codes | 2 | 2 | 0 | 1 | 2 |
| adv_gross_only | 2 | 2 | 0 | 0 | 2 |
| adv_hidden_sheet_only | 1 | 0 | 0 | 0 | 0 |
| adv_id_is_a_group | 2 | 2 | 0 | 0 | 2 |
| adv_identical_planned_actual | 2 | 1 | 0 | 0 | 1 |
| adv_impossible_hours | 2 | 2 | 1 | 0 | 1 |
| adv_kpi_block_first | 2 | 2 | 0 | 1 | 1 |
| adv_kpi_dashboard | 2 | 0 | 0 | 0 | 0 |
| adv_kpi_report_as_bookings | 2 | 0 | 0 | 0 | 0 |
| adv_names_in_department_column | 2 | 2 | 0 | 0 | 2 |
| adv_net_after_commission | 2 | 2 | 0 | 2 | 0 |
| adv_no_description | 1 | 0 | 0 | 0 | 0 |
| adv_payroll_as_costs | 2 | 2 | 0 | 0 | 2 |
| adv_people_as_suppliers | 2 | 2 | 0 | 0 | 2 |
| adv_period_summary_only | 2 | 1 | 0 | 0 | 1 |
| adv_restaurant_sales | 1 | 0 | 0 | 0 | 0 |
| adv_reversed_dates | 2 | 1 | 0 | 0 | 1 |
| adv_revised_planned_hours | 2 | 1 | 0 | 1 | 0 |
| adv_row_counter_number | 2 | 1 | 0 | 0 | 1 |
| adv_staff_under_a_booking_title | 2 | 0 | 0 | 0 | 0 |
| adv_tax_ids_as_number | 1 | 1 | 0 | 0 | 1 |
| adv_utilities_summary | 1 | 0 | 0 | 0 | 0 |
| adv_vat_percent_column | 2 | 2 | 0 | 1 | 1 |
| contact_list | 3 | 0 | 0 | 0 | 0 |
| costs_like_menu | 3 | 0 | 0 | 0 | 0 |
| easy_csv_english | 5 | 5 | 0 | 4 | 1 |
| easy_csv_semicolon | 21 | 18 | 0 | 8 | 10 |
| easy_daily_by_department | 6 | 4 | 1 | 0 | 4 |
| easy_one_hours_column | 6 | 3 | 0 | 2 | 1 |
| easy_xlsx_categories | 5 | 5 | 0 | 2 | 3 |
| easy_xlsx_clean | 10 | 9 | 0 | 8 | 1 |
| easy_xlsx_full_amounts | 5 | 3 | 0 | 2 | 2 |
| easy_xlsx_register | 5 | 5 | 0 | 4 | 1 |
| easy_xlsx_roster | 6 | 4 | 0 | 2 | 3 |
| easy_xlsx_title_block | 6 | 4 | 0 | 0 | 4 |
| easy_xlsx_titled | 5 | 3 | 0 | 3 | 0 |
| easy_xlsx_titles | 10 | 8 | 0 | 8 | 0 |
| hard_ambiguous_date_order | 2 | 1 | 0 | 0 | 1 |
| hard_ambiguous_total | 4 | 1 | 0 | 1 | 0 |
| hard_bare_amount_ask | 3 | 3 | 0 | 1 | 2 |
| hard_bare_ore | 2 | 2 | 0 | 1 | 1 |
| hard_bare_total_beside_net | 3 | 3 | 0 | 0 | 3 |
| hard_category_words_ask | 2 | 1 | 0 | 0 | 1 |
| hard_ci_co_pair | 4 | 4 | 0 | 4 | 0 |
| hard_decoy_summary_below | 5 | 4 | 1 | 4 | 4 |
| hard_decoy_tables | 2 | 0 | 0 | 0 | 0 |
| hard_deep_header | 2 | 2 | 0 | 0 | 2 |
| hard_deep_header_kpi_box | 4 | 3 | 0 | 3 | 0 |
| hard_deep_header_metadata | 2 | 2 | 0 | 1 | 1 |
| hard_grid_ask | 3 | 1 | 0 | 0 | 1 |
| hard_grid_stated | 3 | 1 | 0 | 0 | 1 |
| hard_kpi_band_decoy | 2 | 2 | 0 | 2 | 0 |
| hard_mixed_formats | 4 | 4 | 0 | 4 | 0 |
| hard_relationship_headers | 2 | 2 | 0 | 2 | 0 |
| hard_second_table_ask | 3 | 3 | 0 | 1 | 2 |
| hard_sections | 3 | 2 | 0 | 0 | 2 |
| hard_several_date_columns | 3 | 3 | 0 | 3 | 0 |
| hard_sheet_per_department | 3 | 1 | 0 | 0 | 1 |
| hard_sheet_per_month | 6 | 4 | 0 | 4 | 1 |
| hard_supplier_subtotals | 3 | 3 | 0 | 3 | 0 |
| hard_title_department | 3 | 0 | 0 | 0 | 0 |
| hard_total_contradicts | 2 | 2 | 0 | 0 | 2 |
| hard_totals_contradict | 2 | 2 | 0 | 0 | 2 |
| hard_two_level_header | 11 | 8 | 0 | 5 | 3 |
| hard_two_tables_ask | 2 | 2 | 0 | 0 | 2 |
| inventory | 3 | 3 | 0 | 0 | 3 |
| marketing_report | 3 | 0 | 0 | 0 | 0 |
| medium_categories_dues | 4 | 4 | 0 | 1 | 3 |
| medium_credit_notes | 4 | 4 | 0 | 1 | 3 |
| medium_csv_comma_quoted | 3 | 2 | 0 | 2 | 0 |
| medium_csv_comma_trailing | 3 | 3 | 0 | 1 | 2 |
| medium_csv_dialects | 13 | 10 | 0 | 8 | 2 |
| medium_csv_semicolon_quoted | 3 | 2 | 0 | 2 | 0 |
| medium_csv_tab | 3 | 2 | 0 | 0 | 2 |
| medium_english_export | 5 | 5 | 2 | 2 | 4 |
| medium_extra_sheets | 4 | 3 | 0 | 2 | 1 |
| medium_hidden_extra_sheets | 5 | 2 | 0 | 0 | 2 |
| medium_hidden_summary_sheets | 8 | 7 | 0 | 6 | 1 |
| medium_hourly_rate | 5 | 5 | 0 | 1 | 4 |
| medium_multiline_invoices | 4 | 4 | 0 | 3 | 2 |
| medium_other_hours_and_dates | 5 | 0 | 0 | 0 | 0 |
| medium_personal_data | 17 | 16 | 3 | 10 | 6 |
| medium_reorder_junk | 12 | 12 | 0 | 10 | 2 |
| medium_reorder_noise | 5 | 2 | 1 | 0 | 2 |
| medium_text_formats | 17 | 13 | 1 | 9 | 4 |
| restaurant_sales | 3 | 0 | 0 | 0 | 0 |
| rules_workbook | 3 | 0 | 0 | 0 | 0 |
| todo_sheet | 3 | 0 | 0 | 0 | 0 |
| trial_balance | 3 | 0 | 0 | 0 | 0 |
| web_analytics | 3 | 0 | 0 | 0 | 0 |

## Performance (ms per file)

| Stage | mean | p50 | p95 | max |
|---|---|---|---|---|
| scan | 4.6 | 4.8 | 8.8 | 14.1 |
| understanding | 28.6 | 28.2 | 50.4 | 126.3 |
| mapping | 101.3 | 99.8 | 182.3 | 292.3 |
| total | 134.5 | 132.3 | 232.9 | 360.9 |

## Reading levels (first answer)

ASK 111, BLOCKED 12, MANUAL 198, READY 66
