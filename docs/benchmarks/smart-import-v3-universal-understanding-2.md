# NINFA Smart Import — Universal Understanding Benchmark V2 (AFTER)

Generated 2026-10-29. IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called.

Unseen documents, generated from recipes (none is in the official 240-document corpus), with the truth written next to each file and never read from Smart Import. First upload of each file: no learned profile.

## Corpus

- **402** documents: 360 positives (Prenotazioni 120, Personale 120, Costi 120), 27 negatives, 15 unsupported files.
- Difficulty of the positives: EASY 90, MEDIUM 120, HARD 90, ADVERSARIAL 60.
- 323 xlsx / 79 csv, 34 with several sheets, 126 with personal data, 42 distinct structures.
- sha256 `4497059eced08b9b8e73ab55f87d6fb1ae44279053b87f54c3b9efeebb683bc2`

## Targets

| Target | Wanted | Actual | Met |
|---|---|---|---|
| false automation | == 0 | 0 | yes |
| P0 findings | == 0 | 0 | yes |
| critical wrong mapping (committed) | == 0 | 0 | yes |
| necessary-question recall | >= 1.0 | 1 | yes |
| safe fallback (negatives + unsupported) | >= 1.0 | 1 | yes |
| personal data leaked / not excluded | == 0 | 0 | yes |
| domain accuracy (strict) | >= 0.99 | 0.9944 | yes |
| header accuracy (strict) | >= 0.99 | 1 | yes |
| table accuracy (strict) | >= 0.99 | 1 | yes |
| required precision | >= 0.995 | 0.994 | **NO** |
| required precision, committed claims | >= 0.995 | 0.9982 | yes |
| required recall | >= 0.99 | 1 | yes |

## Results by group (positive documents)

Domain / header / table are STRICT: a document the engine could not read counts as a miss. FA = false automation. Crit. wrong = a CERTAIN wrong reading of a fact a business decision rests on. Necessary Q = recall of the questions a person must be asked.

| Group | Docs | Domain | Header | Table | Req. prec. | Req. recall | Opt. prec. | FA | Crit. wrong (committed) | Zero-question | Necessary Q | Unneeded Q | PII | P0 | P1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| All positives | 360 | 99.4% | 100.0% | 100.0% | 99.40% | 100.0% | 99.7% | 0 | 0 | 94.8% | 100.0% | 23 | 0 | 0 | 1 |
| Prenotazioni | 120 | 100.0% | 100.0% | 100.0% | 99.27% | 100.0% | 100.0% | 0 | 0 | 100.0% | 100.0% | 1 | 0 | 0 | 1 |
| Personale | 120 | 99.2% | 100.0% | 100.0% | 100.00% | 100.0% | n/a | 0 | 0 | 94.6% | 100.0% | 6 | 0 | 0 | 0 |
| Costi | 120 | 99.2% | 100.0% | 100.0% | 99.10% | 100.0% | 99.3% | 0 | 0 | 89.1% | 100.0% | 16 | 0 | 0 | 0 |
| EASY | 90 | 100.0% | 100.0% | 100.0% | 100.00% | 100.0% | 100.0% | 0 | 0 | 94.4% | n/a | 5 | 0 | 0 | 0 |
| MEDIUM | 120 | 100.0% | 100.0% | 100.0% | 100.00% | 100.0% | 100.0% | 0 | 0 | 95.8% | n/a | 5 | 0 | 0 | 0 |
| HARD | 90 | 100.0% | 100.0% | 100.0% | 99.32% | 100.0% | 100.0% | 0 | 0 | 92.3% | 100.0% | 3 | 0 | 0 | 0 |
| ADVERSARIAL | 60 | 96.4% | 100.0% | 100.0% | 96.13% | 100.0% | 97.7% | 0 | 0 | 100.0% | 100.0% | 10 | 0 | 0 | 1 |

## Negatives and unsupported files

- Negative office documents (27): safe fallback 27/27, offered as automatic 0.
- Unsupported files (15): clean refusal 15/15.

Wrong readings of a critical fact at ANY level (a LOW guess the person is asked about counts too): 1; committed (certain and not asked): 0.

## Findings

| Severity | Findings | Documents (worst) |
|---|---|---|
| P0 | 0 | 0 |
| P1 | 1 | 1 |
| P2 | 31 | 25 |
| P3 | 0 | 0 |

| Category | Findings | Documents |
|---|---|---|
| DOMAIN_WRONG | 5 | 5 |
| FIELD_WRONG | 2 | 2 |
| QUESTION_UNNECESSARY | 25 | 24 |

## By recipe

| Recipe | Docs | With findings | P0 | P1 | P2 |
|---|---|---|---|---|---|
| adv_ambiguous_date_order | 4 | 0 | 0 | 0 | 0 |
| adv_bank_statement | 2 | 0 | 0 | 0 | 0 |
| adv_bare_rate_next_to_hours | 2 | 0 | 0 | 0 | 0 |
| adv_bookings_under_costs_title | 1 | 1 | 0 | 0 | 1 |
| adv_bookings_under_staff_title | 2 | 0 | 0 | 0 | 0 |
| adv_country_as_source | 2 | 0 | 0 | 0 | 0 |
| adv_data_on_a_hidden_sheet | 4 | 0 | 0 | 0 | 0 |
| adv_decoy_columns | 2 | 0 | 0 | 0 | 0 |
| adv_department_codes | 2 | 0 | 0 | 0 | 0 |
| adv_gross_only | 2 | 0 | 0 | 0 | 0 |
| adv_hidden_sheet_only | 1 | 0 | 0 | 0 | 0 |
| adv_id_is_a_group | 2 | 1 | 0 | 1 | 1 |
| adv_identical_planned_actual | 2 | 0 | 0 | 0 | 0 |
| adv_impossible_hours | 2 | 2 | 0 | 0 | 2 |
| adv_kpi_block_first | 2 | 0 | 0 | 0 | 0 |
| adv_kpi_dashboard | 2 | 0 | 0 | 0 | 0 |
| adv_kpi_report_as_bookings | 2 | 0 | 0 | 0 | 0 |
| adv_names_in_department_column | 2 | 2 | 0 | 0 | 2 |
| adv_net_after_commission | 2 | 0 | 0 | 0 | 0 |
| adv_no_description | 1 | 0 | 0 | 0 | 0 |
| adv_payroll_as_costs | 2 | 0 | 0 | 0 | 0 |
| adv_people_as_suppliers | 2 | 2 | 0 | 0 | 2 |
| adv_period_summary_only | 2 | 1 | 0 | 0 | 1 |
| adv_restaurant_sales | 1 | 1 | 0 | 0 | 1 |
| adv_reversed_dates | 2 | 0 | 0 | 0 | 0 |
| adv_revised_planned_hours | 2 | 0 | 0 | 0 | 0 |
| adv_row_counter_number | 2 | 0 | 0 | 0 | 0 |
| adv_staff_under_a_booking_title | 2 | 0 | 0 | 0 | 0 |
| adv_tax_ids_as_number | 1 | 0 | 0 | 0 | 0 |
| adv_utilities_summary | 1 | 0 | 0 | 0 | 0 |
| adv_vat_percent_column | 2 | 0 | 0 | 0 | 0 |
| contact_list | 3 | 0 | 0 | 0 | 0 |
| costs_like_menu | 3 | 0 | 0 | 0 | 0 |
| easy_csv_english | 5 | 0 | 0 | 0 | 0 |
| easy_csv_semicolon | 21 | 0 | 0 | 0 | 0 |
| easy_daily_by_department | 6 | 0 | 0 | 0 | 0 |
| easy_one_hours_column | 6 | 0 | 0 | 0 | 0 |
| easy_xlsx_categories | 5 | 5 | 0 | 0 | 5 |
| easy_xlsx_clean | 10 | 0 | 0 | 0 | 0 |
| easy_xlsx_full_amounts | 5 | 0 | 0 | 0 | 0 |
| easy_xlsx_register | 5 | 0 | 0 | 0 | 0 |
| easy_xlsx_roster | 6 | 0 | 0 | 0 | 0 |
| easy_xlsx_title_block | 6 | 0 | 0 | 0 | 0 |
| easy_xlsx_titled | 5 | 0 | 0 | 0 | 0 |
| easy_xlsx_titles | 10 | 0 | 0 | 0 | 0 |
| hard_ambiguous_date_order | 2 | 0 | 0 | 0 | 0 |
| hard_ambiguous_total | 4 | 0 | 0 | 0 | 0 |
| hard_bare_amount_ask | 3 | 2 | 0 | 0 | 2 |
| hard_bare_ore | 2 | 0 | 0 | 0 | 0 |
| hard_bare_total_beside_net | 3 | 0 | 0 | 0 | 0 |
| hard_category_words_ask | 2 | 0 | 0 | 0 | 0 |
| hard_ci_co_pair | 4 | 0 | 0 | 0 | 0 |
| hard_decoy_summary_below | 5 | 0 | 0 | 0 | 0 |
| hard_decoy_tables | 2 | 0 | 0 | 0 | 0 |
| hard_deep_header | 2 | 0 | 0 | 0 | 0 |
| hard_deep_header_kpi_box | 4 | 0 | 0 | 0 | 0 |
| hard_deep_header_metadata | 2 | 0 | 0 | 0 | 0 |
| hard_grid_ask | 3 | 0 | 0 | 0 | 0 |
| hard_grid_stated | 3 | 0 | 0 | 0 | 0 |
| hard_kpi_band_decoy | 2 | 1 | 0 | 0 | 1 |
| hard_mixed_formats | 4 | 0 | 0 | 0 | 0 |
| hard_relationship_headers | 2 | 0 | 0 | 0 | 0 |
| hard_second_table_ask | 3 | 0 | 0 | 0 | 0 |
| hard_sections | 3 | 0 | 0 | 0 | 0 |
| hard_several_date_columns | 3 | 0 | 0 | 0 | 0 |
| hard_sheet_per_department | 3 | 0 | 0 | 0 | 0 |
| hard_sheet_per_month | 6 | 0 | 0 | 0 | 0 |
| hard_supplier_subtotals | 3 | 0 | 0 | 0 | 0 |
| hard_title_department | 3 | 0 | 0 | 0 | 0 |
| hard_total_contradicts | 2 | 0 | 0 | 0 | 0 |
| hard_totals_contradict | 2 | 0 | 0 | 0 | 0 |
| hard_two_level_header | 11 | 0 | 0 | 0 | 0 |
| hard_two_tables_ask | 2 | 0 | 0 | 0 | 0 |
| inventory | 3 | 3 | 0 | 0 | 3 |
| marketing_report | 3 | 0 | 0 | 0 | 0 |
| medium_categories_dues | 4 | 4 | 0 | 0 | 4 |
| medium_credit_notes | 4 | 0 | 0 | 0 | 0 |
| medium_csv_comma_quoted | 3 | 0 | 0 | 0 | 0 |
| medium_csv_comma_trailing | 3 | 0 | 0 | 0 | 0 |
| medium_csv_dialects | 13 | 0 | 0 | 0 | 0 |
| medium_csv_semicolon_quoted | 3 | 0 | 0 | 0 | 0 |
| medium_csv_tab | 3 | 0 | 0 | 0 | 0 |
| medium_english_export | 5 | 0 | 0 | 0 | 0 |
| medium_extra_sheets | 4 | 0 | 0 | 0 | 0 |
| medium_hidden_extra_sheets | 5 | 0 | 0 | 0 | 0 |
| medium_hidden_summary_sheets | 8 | 0 | 0 | 0 | 0 |
| medium_hourly_rate | 5 | 0 | 0 | 0 | 0 |
| medium_multiline_invoices | 4 | 0 | 0 | 0 | 0 |
| medium_other_hours_and_dates | 5 | 0 | 0 | 0 | 0 |
| medium_personal_data | 17 | 0 | 0 | 0 | 0 |
| medium_reorder_junk | 12 | 0 | 0 | 0 | 0 |
| medium_reorder_noise | 5 | 0 | 0 | 0 | 0 |
| medium_text_formats | 17 | 1 | 0 | 0 | 1 |
| restaurant_sales | 3 | 0 | 0 | 0 | 0 |
| rules_workbook | 3 | 0 | 0 | 0 | 0 |
| todo_sheet | 3 | 0 | 0 | 0 | 0 |
| trial_balance | 3 | 0 | 0 | 0 | 0 |
| web_analytics | 3 | 0 | 0 | 0 | 0 |

## Performance (ms per file)

| Stage | mean | p50 | p95 | max |
|---|---|---|---|---|
| scan | 4.0 | 4.4 | 7.3 | 11.9 |
| understanding | 26.0 | 25.2 | 46.1 | 90.7 |
| mapping | 93.8 | 93.0 | 169.1 | 248.3 |
| total | 123.8 | 121.6 | 219.2 | 299.4 |

## Reading levels (first answer)

ASK 53, BLOCKED 14, MANUAL 44, READY 276
