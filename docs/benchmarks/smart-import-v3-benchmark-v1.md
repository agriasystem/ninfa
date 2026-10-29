# Smart Import V3 - Intelligence Benchmark V1

Baseline: `main` = `48a1a656edc98b15665153c0d7322411f1a46988` (Smart Import V3.0, merged). Assistant: **off** - IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called. Run on 240 synthetic documents, 2026-10-29.

Rerun with one command, from `services/api`: `python -m tests.benchmarks.smart_import_v3` (console summary + JSON in `tests/benchmarks/results/` + this report). Nothing is read from or written to a database, nothing leaves the process, no model is called.

## 1. Result

Targets are the ones the benchmark was asked to compare against; nothing was changed to reach them.

| Metric | Target | Total | Personale | Prenotazioni | Costi | Total vs target |
|---|---|---|---|---|---|---|
| False automation rate | <= 0% | 0.0% (0/240) | 0.0% (0/88) | 0.0% (0/80) | 0.0% (0/72) | met |
| Zero-question correctness | >= 100% | 98.1% (151/154) | 100.0% (59/59) | 97.9% (47/48) | 95.7% (45/47) | **missed** |
| Personal columns left out | >= 100% | 100.0% (108/108) | 100.0% (94/94) | 100.0% (13/13) | 100.0% (1/1) | met |
| Domain accuracy | >= 98% | 98.7% (235/238) | 98.9% (86/87) | 97.5% (78/80) | 100.0% (71/71) | met |
| Header accuracy | >= 98% | 100.0% (235/235) | 100.0% (86/86) | 100.0% (78/78) | 100.0% (71/71) | met |
| Required-field precision | >= 99% | 99.8% (1022/1024) | 100.0% (290/290) | 99.5% (428/430) | 100.0% (304/304) | met |
| Required-field recall | >= 95% | 99.8% (1022/1024) | 100.0% (290/290) | 99.5% (428/430) | 100.0% (304/304) | met |
| Safe fallback (documents to refuse) | >= 100% | 100.0% (58/58) | 100.0% (15/15) | 100.0% (23/23) | 100.0% (20/20) | met |

**False automation: 0 of 240 documents (0.0%)** - offered as automatic (a summary and one button) while the reading differs from the truth in a business-critical field, or while the document should never have been automatic. They are listed in section 3.

## 2. Corpus

|  |  |
|---|---|
| Documents | 240 |
| Personale | 88 |
| Prenotazioni | 80 |
| Costi | 72 |
| Excel / CSV | 224 / 16 |
| Office-realistic (merged cells, colours, notes, odd headers...) | 66 |
| Negative (incomplete, ambiguous, malformed, out of domain, contradictory) | 58 |
| Adversarial (instructions, formulas, HTML, long cells, hidden sheets...) | 19 |
| With personal data | 94 |
| More than one sheet | 14 |
| Large (1,600 - 3,200 rows) | 3 |
| Distinct structure signatures | 38 |
| Expected outcome | ASK 19, NOT_AUTOMATIC 27, READY 163, REJECT 29, WARN 2 |
| Corpus hash (sha256) | `6262d3b06dfe9db6...` |

## 3. False automation

No document was offered as automatic with a wrong reading.

## 4. Zero-question audit

154 documents ended READY; 154 of them with no question and no blocker (automatic). Every one is listed.

| Document | Card | Totally correct? | What was wrong |
|---|---|---|---|
| `B36_two_level_header` | bookings | **NOT correct** | FIELD_MISSED: total_revenue not recognised |
| `C17_everyday_category_words_luce_acqua_gas` | costs | **NOT correct** | FIELD_MISSED: cost_category not recognised |
| `C33_credit_notes_negative_amounts` | costs | **NOT correct** | FIELD_MISSED: document_type not recognised |
| `B01_csv_italian_canonical` | bookings | correct | - |
| `B02_npren_prenotato_il_dal_al` | bookings | correct | - |
| `B04_english_reservation_id_creation_date` | bookings | correct | - |
| `B06_ref_portale_totale_soggiorno` | bookings | correct | - |
| `B07_room_revenue_and_total_stay_both` | bookings | correct | - |
| `B08_abbreviated_headers` | bookings | correct | - |
| `B09_mixed_italian_english_headers` | bookings | correct | - |
| `B10_guest_name_email_phone_notes` | bookings | correct | - |
| `B11_guest_column_holds_names_not_a_count` | bookings | correct | - |
| `B12_guests_count_column_and_guest_name` | bookings | correct | - |
| `B13_pax_and_num_ospiti` | bookings | correct | - |
| `B15_title_before_table` | bookings | correct | - |
| `B16_notes_below_the_table` | bookings | correct | - |
| `B17_summary_block_before_table` | bookings | correct | - |
| `B18_totals_row_and_channel_subtotals` | bookings | correct | - |
| `B19_dashboard_bookings_and_legend_sheets` | bookings | correct | - |
| `B20_sheet_per_month_same_columns` | bookings | correct | - |
| `B22_status_and_cancellation_date` | bookings | correct | - |
| `B24_channels_direct_phone_email_walkin` | bookings | correct | - |
| `B25_ota_channels_with_commission_columns` | bookings | correct | - |
| `B26_amounts_thousands_dot_comma_decimal` | bookings | correct | - |
| `B27_amounts_point_decimal_csv` | bookings | correct | - |
| `B28_amounts_with_euro_sign_text` | bookings | correct | - |
| `B29_amounts_excel_currency_format` | bookings | correct | - |
| `B30_dates_text_italian` | bookings | correct | - |
| `B31_dates_us_provable_csv` | bookings | correct | - |
| `B33_dates_dotted_and_day_month_name` | bookings | correct | - |
| `B34_dates_day_month_name_text` | bookings | correct | - |
| `B35_booking_timestamp_with_time` | bookings | correct | - |
| `B38_reordered_columns_with_junk` | bookings | correct | - |
| `B39_ids_with_leading_zeros_and_numeric` | bookings | correct | - |
| `B40_office_pms_export_colored_header` | bookings | correct | - |
| `B43_office_repeated_header_every_page` | bookings | correct | - |
| `B60_adv_hidden_sheet_with_older_bookings` | bookings | correct | - |
| `B61_adv_instructions_in_guest_notes` | bookings | correct | - |
| `B62_adv_formulas_and_html_in_cells` | bookings | correct | - |
| `B63_adv_total_word_in_a_notes_column` | bookings | correct | - |
| `B65_adv_very_long_cells_and_unicode` | bookings | correct | - |
| `B66_large_year_of_bookings` | bookings | correct | - |
| `BO05_kpi_block_beside_the_table` | bookings | correct | - |
| `BO06_table_starts_in_column_c_frozen_panes` | bookings | correct | - |
| `BO07_weekday_prefixed_dates` | bookings | correct | - |
| `BO08_room_and_breakfast_revenue_columns` | bookings | correct | - |
| `BO10_one_sheet_per_week` | bookings | correct | - |
| `BO11_header_cells_with_line_breaks` | bookings | correct | - |
| `BO12_channel_merged_down_the_column` | bookings | correct | - |
| `BO13_blank_row_between_every_record` | bookings | correct | - |
| `C01_complete_register_consistent` | costs | correct | - |
| `C02_english_amount_excl_vat` | costs | correct | - |
| `C03_totale_netto_imposta_totale` | costs | correct | - |
| `C04_imponibile_iva_lordo` | costs | correct | - |
| `C05_net_vat_gross_amount_english` | costs | correct | - |
| `C06_netto_only` | costs | correct | - |
| `C07_imponibile_only` | costs | correct | - |
| `C08_net_vat_total_do_not_add_up` | costs | correct (contradiction shown as a warning) | - |
| `C16_eight_known_categories` | costs | correct | - |
| `C19_no_category_column` | costs | correct | - |
| `C20_title_before_table` | costs | correct | - |
| `C21_total_row_correct` | costs | correct | - |
| `C22_summary_block_before_table` | costs | correct | - |
| `C23_subtotals_per_category` | costs | correct | - |
| `C24_summary_sheet_and_register_sheet` | costs | correct | - |
| `C25_supplier_directory_sheet_and_invoices_sheet` | costs | correct | - |
| `C26_sheet_per_month_same_columns` | costs | correct | - |
| `C27_dates_text_italian` | costs | correct | - |
| `C28_dates_iso_csv` | costs | correct | - |
| `C30_amounts_italian_thousands` | costs | correct | - |
| `C31_amounts_us_thousands_csv` | costs | correct | - |
| `C32_amounts_euro_sign_text` | costs | correct | - |
| `C34_currency_symbol_and_codes` | costs | correct | - |
| `C35_no_currency_column` | costs | correct | - |
| `C36_document_number_styles` | costs | correct | - |
| `C37_vat_number_and_due_date_columns` | costs | correct | - |
| `C38_several_lines_per_invoice` | costs | correct | - |
| `C39_total_word_inside_a_description` | costs | correct | - |
| `C40_two_level_header_importi` | costs | correct | - |
| `C43_reordered_with_junk_columns` | costs | correct | - |
| `C44_office_accounting_export_header_on_row_five` | costs | correct | - |
| `C45_office_cost_ledger_csv_semicolon` | costs | correct | - |
| `C47_office_supplier_invoices_with_notes` | costs | correct | - |
| `C55_adv_hidden_sheet_with_other_invoices` | costs | correct | - |
| `C56_adv_instructions_in_descriptions` | costs | correct | - |
| `C57_adv_formulas_html_and_unicode` | costs | correct | - |
| `C58_adv_very_long_description_cell` | costs | correct | - |
| `C59_large_year_of_invoices` | costs | correct | - |
| `CO01_protocol_number_and_supplier_document_number` | costs | correct | - |
| `CO03_cost_centre_and_department_columns` | costs | correct | - |
| `CO08_supplier_cells_merged_down_the_column` | costs | correct | - |
| `CO09_amounts_with_eur_suffix_text` | costs | correct | - |
| `CO10_header_cells_with_line_breaks` | costs | correct | - |
| `CO11_blank_row_between_every_record` | costs | correct | - |
| `CO12_attachment_and_approval_columns` | costs | correct | - |
| `L01_csv_basic` | labor | correct | - |
| `L02_xlsx_giorno_area` | labor | correct | - |
| `L03_alias_settore_pianificate_lavorate` | labor | correct | - |
| `L04_alias_dept_hprev_consuntivo` | labor | correct | - |
| `L05_english_planned_actual` | labor | correct | - |
| `L06_english_scheduled_worked` | labor | correct | - |
| `L07_reparto_slash_mansione_ore_prog` | labor | correct | - |
| `L08_reparto_o_mansione_with_hourly_rate` | labor | correct | - |
| `L09_centro_operativo` | labor | correct | - |
| `L10_only_planned_hours` | labor | correct | - |
| `L11_only_actual_hours` | labor | correct | - |
| `L12_reordered_with_junk_columns` | labor | correct | - |
| `L13_title_block_before_table` | labor | correct | - |
| `L14_summary_block_before_table` | labor | correct | - |
| `L15_summary_block_after_table` | labor | correct | - |
| `L16_total_row_correct` | labor | correct | - |
| `L17_subtotals_per_department` | labor | correct | - |
| `L18_sheet_per_department` | labor | correct | - |
| `L20_department_as_section_lines` | labor | correct | - |
| `L21_sections_with_totals_and_notes` | labor | correct | - |
| `L22_two_level_header` | labor | correct | - |
| `L23_two_level_header_hours_over_planned_actual` | labor | correct | - |
| `L26_grid_real_dates_basis_stated` | labor | correct | - |
| `L28_grid_weekdays_period_in_title` | labor | correct | - |
| `L29_grid_three_weekdays_period_in_title` | labor | correct | - |
| `L39_known_italian_department_words` | labor | correct | - |
| `L40_vocabulary_restaurant_bar_governante` | labor | correct | - |
| `L41_pii_split_name_email_phone_taxcode` | labor | correct | - |
| `L42_pii_name_and_company_email` | labor | correct | - |
| `L43_dates_us_provable` | labor | correct | - |
| `L45_dates_weekday_prefix_text` | labor | correct | - |
| `L46_dates_dotted_text_hours_comma` | labor | correct | - |
| `L47_rates_and_costs_columns` | labor | correct | - |
| `L49_decoy_legend_table_before_real_one` | labor | correct | - |
| `L50_hidden_draft_sheet_and_visible_sheet` | labor | correct | - |
| `L51_summary_sheet_first_then_detail` | labor | correct | - |
| `L52_dashboard_sheet_and_data_sheet` | labor | correct | - |
| `L53_header_on_row_nine_after_long_preamble` | labor | correct | - |
| `L54_office_weekly_roster_final` | labor | correct | - |
| `L55_office_monthly_hours_report` | labor | correct | - |
| `L57_office_kitchen_and_restaurant_two_sheets` | labor | correct | - |
| `L58_office_names_in_two_columns_and_comments` | labor | correct | - |
| `L61_neg_totals_row_contradicts_rows` | labor | correct (contradiction shown as a warning) | - |
| `L67_adv_prompt_injection_in_cells` | labor | correct | - |
| `L68_adv_formulas_html_and_unicode` | labor | correct | - |
| `L69_adv_very_long_cell_and_odd_headers` | labor | correct | - |
| `L70_adv_example_table_before_real_table` | labor | correct | - |
| `L72_large_three_months_roster` | labor | correct | - |
| `LO04_weekday_name_and_date_in_two_columns` | labor | correct | - |
| `LO05_future_days_have_no_actual_hours_yet` | labor | correct | - |
| `LO06_job_titles_in_qualifica_column` | labor | correct | - |
| `LO07_department_in_a_label_value_block` | labor | correct | - |
| `LO08_one_sheet_per_week_sett43_sett44` | labor | correct | - |
| `LO09_legend_block_drawn_beside_the_table` | labor | correct | - |
| `LO11_department_cells_merged_down_the_column` | labor | correct | - |
| `LO12_blank_row_between_every_record` | labor | correct | - |
| `LO13_hours_written_with_a_unit` | labor | correct | - |
| `LO14_header_cells_with_line_breaks` | labor | correct | - |
| `LO16_extra_numeric_columns_overtime_leave` | labor | correct | - |

## 5. All metrics

| Metric | Total | Personale | Prenotazioni | Costi |
|---|---|---|---|---|
| Domain accuracy | 98.7% (235/238) | 98.9% (86/87) | 97.5% (78/80) | 100.0% (71/71) |
| Sheet selection accuracy (multi-sheet documents) | 100.0% (14/14) | 100.0% (6/6) | 100.0% (4/4) | 100.0% (4/4) |
| Header detection accuracy | 100.0% (235/235) | 100.0% (86/86) | 100.0% (78/78) | 100.0% (71/71) |
| Table boundary accuracy (first record + number of records) | 100.0% (235/235) | 100.0% (86/86) | 100.0% (78/78) | 100.0% (71/71) |
| Required-field precision (every claim) | 99.8% (1022/1024) | 100.0% (290/290) | 99.5% (428/430) | 100.0% (304/304) |
| Required-field precision (claims without a question) | 100.0% (1019/1019) | 100.0% (290/290) | 100.0% (425/425) | 100.0% (304/304) |
| Required-field recall | 99.8% (1022/1024) | 100.0% (290/290) | 99.5% (428/430) | 100.0% (304/304) |
| Required-field recall, counting columns the person is asked about | 99.8% (1022/1024) | 100.0% (290/290) | 99.5% (428/430) | 100.0% (304/304) |
| All-fields precision | 99.8% (1225/1227) | 100.0% (292/292) | 99.6% (569/571) | 100.0% (364/364) |
| All-fields recall | 99.5% (1225/1231) | 100.0% (292/292) | 99.5% (569/572) | 99.2% (364/367) |
| Personal columns left out of the import | 100.0% (108/108) | 100.0% (94/94) | 100.0% (13/13) | 100.0% (1/1) |
| Zero-question coverage | 64.2% (154/240) | 67.0% (59/88) | 60.0% (48/80) | 65.3% (47/72) |
| Zero-question correctness | 98.1% (151/154) | 100.0% (59/59) | 97.9% (47/48) | 95.7% (45/47) |
| FALSE AUTOMATION RATE (of all documents) | 0.0% (0/240) | 0.0% (0/88) | 0.0% (0/80) | 0.0% (0/72) |
| False automation, of the documents offered as automatic | 0.0% (0/154) | 0.0% (0/59) | 0.0% (0/48) | 0.0% (0/47) |
| Necessary-question recall | 100.0% (25/25) | 100.0% (13/13) | 100.0% (5/5) | 100.0% (7/7) |
| Unnecessary-question rate (of the questions asked) | 2.1% (1/48) | 4.3% (1/23) | 0.0% (0/16) | 0.0% (0/9) |
| Safe fallback (not automatic) | 100.0% (58/58) | 100.0% (15/15) | 100.0% (23/23) | 100.0% (20/20) |
| Safe fallback, strict (refusal documents ending manual or blocked) | 100.0% (29/29) | 100.0% (9/9) | 100.0% (8/8) | 100.0% (12/12) |
| Conversations that end in an automatic import | 100.0% (30/30) | 100.0% (15/15) | 100.0% (9/9) | 100.0% (6/6) |
| ...and end with the right reading | 100.0% (30/30) | 100.0% (15/15) | 100.0% (9/9) | 100.0% (6/6) |
| Documents | 240 | 88 | 80 | 72 |
| Documents with a false automation | 0 | 0 | 0 | 0 |
| Personal values found in what is sent to the browser | 0 | 0 | 0 | 0 |
| Documents with such a leak | 0 | 0 | 0 | 0 |
| Junk columns that became a field | 0 | 0 | 0 | 0 |
| Questions asked / unnecessary | 48 / 1 | 23 / 1 | 16 / 0 | 9 / 0 |
| Documents with at least one unnecessary question | 1 | 1 | 0 | 0 |
| Department words asked about that needed no question | 12 | 9 | 3 | 0 |
| Department words decided silently | 0 | 0 | 0 | 0 |
| Department words read as the wrong category | 0 | 0 | 0 | 0 |
| Automatic with a visible warning | 3 | 1 | 0 | 2 |
| Rounds of answers needed (mean) | 1.0 | 1.1 | 1.0 | 1.0 |

## 6. Questions

Necessary questions: asked 100.0% (25/25). Missing: none.

Unnecessary questions by kind (every question the truth does not need or tolerate):

| Card | Kind | Questions |
|---|---|---|
| labor | DEPARTMENT_ROWS | 1 |

The most frequent single causes (kind and column):

| Card | Question | Times |
|---|---|---|

## 7. Personal data

Personal columns left out of the import: 100.0% (108/108).
Personal values that appear in what the API sends to the browser: 0 (in 0 documents, out of 740 values checked).
What would be shown to a language model, if one were configured: 22 documents would reach it (22 calls recorded, nothing sent anywhere); personal values in that evidence: 0.


## 8. Results by kind of data

### Personale

88 documents; levels {'READY': 59, 'ASK': 17, 'MANUAL': 5, 'BLOCKED': 7}; findings by worst severity {'P0': 0, 'P1': 0, 'P2': 2, 'P3': 0}; clean documents 86.

| Metric | Value |
|---|---|
| Domain accuracy | 98.9% (86/87) |
| Header accuracy | 100.0% (86/86) |
| Table boundary accuracy | 100.0% (86/86) |
| Required precision / recall | 100.0% (290/290) / 100.0% (290/290) |
| Zero-question coverage / correctness | 67.0% (59/88) / 100.0% (59/59) |
| False automation | 0 (0.0% (0/88)) |
| Necessary-question recall | 100.0% (13/13) |
| Unnecessary-question rate | 4.3% (1/23) |
| Safe fallback | 100.0% (15/15) |
| Wrong-card probe (uploaded on another card) | 73 documents: automatic 0, asked 'what kind of data' 73 |

### Prenotazioni

80 documents; levels {'READY': 48, 'MANUAL': 19, 'ASK': 12, 'BLOCKED': 1}; findings by worst severity {'P0': 0, 'P1': 0, 'P2': 5, 'P3': 0}; clean documents 75.

| Metric | Value |
|---|---|
| Domain accuracy | 97.5% (78/80) |
| Header accuracy | 100.0% (78/78) |
| Table boundary accuracy | 100.0% (78/78) |
| Required precision / recall | 99.5% (428/430) / 99.5% (428/430) |
| Zero-question coverage / correctness | 60.0% (48/80) / 97.9% (47/48) |
| False automation | 0 (0.0% (0/80)) |
| Necessary-question recall | 100.0% (5/5) |
| Unnecessary-question rate | 0.0% (0/16) |
| Safe fallback | 100.0% (23/23) |
| Wrong-card probe (uploaded on another card) | 57 documents: automatic 0, asked 'what kind of data' 57 |

### Costi

72 documents; levels {'READY': 47, 'ASK': 5, 'MANUAL': 16, 'BLOCKED': 4}; findings by worst severity {'P0': 0, 'P1': 0, 'P2': 3, 'P3': 0}; clean documents 69.

| Metric | Value |
|---|---|
| Domain accuracy | 100.0% (71/71) |
| Header accuracy | 100.0% (71/71) |
| Table boundary accuracy | 100.0% (71/71) |
| Required precision / recall | 100.0% (304/304) / 100.0% (304/304) |
| Zero-question coverage / correctness | 65.3% (47/72) / 95.7% (45/47) |
| False automation | 0 (0.0% (0/72)) |
| Necessary-question recall | 100.0% (7/7) |
| Unnecessary-question rate | 0.0% (0/9) |
| Safe fallback | 100.0% (20/20) |
| Wrong-card probe (uploaded on another card) | 52 documents: automatic 0, asked 'what kind of data' 52 |

## 9. Performance

Baseline only, nothing optimised. Timing is the median of 3 calls per document after a warm-up; memory is the peak of Python allocations (`tracemalloc`) of one call. Mean 140 ms, p50 114 ms, p95 196 ms, max 2119 ms per document.

|  | mean ms | p50 ms | p95 ms | max ms | peak Python memory MiB (p50 / max) | file KiB (p50 / max) |
|---|---|---|---|---|---|---|
| total | 140 | 114 | 196 | 2119 | 0.5 / 12.6 | 5.7 / 137 |
| Personale | 105 | 82 | 147 | 1476 | 0.5 / 4.7 | 5.5 / 40 |
| Prenotazioni | 176 | 152 | 217 | 2001 | 0.6 / 12.6 | 5.9 / 137 |
| Costi | 145 | 112 | 177 | 2119 | 0.5 / 10.2 | 5.9 / 120 |

## 10. Confusion report and failure modes

Findings by category - the figure in brackets is the number of documents. Every finding of every document is in Appendix A.

| Category | Total | Personale | Prenotazioni | Costi |
|---|---|---|---|---|
| DOMAIN_WRONG | 3 (3) | 1 (1) | 2 (2) | 0 (0) |
| SHEET_WRONG | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| HEADER_WRONG | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| TABLE_BOUNDARY_WRONG | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| FIELD_WRONG | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| FIELD_MISSED | 6 (6) | 0 (0) | 3 (3) | 3 (3) |
| PII_LEAK | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| QUESTION_MISSING | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| QUESTION_UNNECESSARY | 1 (1) | 1 (1) | 0 (0) | 0 (0) |
| FALSE_ZERO_QUESTION | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| UNSAFE_IMPORT | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| EXPECTED_REJECTION | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| OTHER | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

Failure modes: findings grouped by category and field (or question kind), worst severity first. P0 = silent wrong data, P1 = blocks a valid file, P2 = needless friction, P3 = edge case.

| Worst severity | Category | Field / kind | Documents | Examples |
|---|---|---|---|---|
| P2 | DOMAIN_WRONG | - | 3 | `L32_grid_generic_day_columns`, `B51_neg_occupancy_calendar_not_bookings`, `BO02_arrivals_by_day_sections_no_ids` |
| P2 | FIELD_MISSED | room_revenue | 2 | `B44_office_airbnb_style_export_no_channel_column`, `BO04_front_desk_arrivals_list_no_booking_date` |
| P2 | QUESTION_UNNECESSARY | DEPARTMENT_ROWS | 1 | `L62_neg_swapped_header_labels` |
| P2 | FIELD_MISSED | total_revenue | 1 | `B36_two_level_header` |
| P2 | FIELD_MISSED | cost_category | 1 | `C17_everyday_category_words_luce_acqua_gas` |
| P2 | FIELD_MISSED | document_type | 1 | `C33_credit_notes_negative_amounts` |
| P2 | FIELD_MISSED | invoice_gross_amount | 1 | `CO02_payment_schedule_not_a_register` |

Headers the truth says are a business field and NINFA did not recognise:

| Card | Field | Header not recognised | Documents |
|---|---|---|---|
| bookings | room_revenue | 'Earnings' | `B44_office_airbnb_style_export_no_channel_column` |
| bookings | room_revenue | 'Tot. €' | `BO04_front_desk_arrivals_list_no_booking_date` |
| bookings | total_revenue | 'Importi / Totale' | `B36_two_level_header` |
| costs | cost_category | 'Voce' | `C17_everyday_category_words_luce_acqua_gas` |
| costs | document_type | 'Tipo' | `C33_credit_notes_negative_amounts` |
| costs | invoice_gross_amount | 'Importo da pagare' | `CO02_payment_schedule_not_a_register` |

## 11. Interpretation

This section is written by hand from the numbers above; the numbers themselves are regenerated by
every run. It says what the numbers mean for the product, not how to fix it: nothing in
Smart Import was changed for this benchmark.

### What the benchmark shows

Smart Import V3 reads documents well, and it is **careful in the way that matters most**: of the
240 documents, 58 should not be imported automatically (refusals, contradictions, other kinds of
data). 54 were not offered as automatic; 2 were, with the contradiction shown as a warning - which
the brief accepts; 2 were offered silently (`C42`, `CO04`, below). The 182 documents that can be
imported, uploaded on a *wrong* card, were all sent to "what kind of data is this?" and none became
automatic. Hostile content
(instructions in cells and titles, formulas, HTML, a right-to-left override, zero-width characters,
24,000-character cells, hidden sheets) changed nothing: no document was misread *because of* what it
said. Text dates and amounts in 40 documents of known convention (day-first, month-first, ISO, dots,
`1.237,45`, `1,234.56`, euro signs) were all resolved as written, and the ambiguous ones
(`03/04`) were asked about. Sheet selection was right 14 times out of 14.

It is **not yet robust enough to be trusted without looking**: 5 documents (2.1% of the corpus,
6.2% of the 81 it offered as automatic) were offered as "a summary and one button" with a reading
that is wrong or incomplete in a critical field. The target was none.

### P0 - silent wrong data (10 documents have a P0 finding; 5 were offered as automatic)

1. **A table that stops before it ends.** The most serious finding, because nothing on the screen
   hints at it.
   - A one-cell text line inside the table is taken for a note, and everything after a note is
     skipped. A printed report with a `--- pagina successiva ---` line every 8 records was offered
     as automatic with **8 of its 24 records** (`B43_office_repeated_header_every_page`).
   - A booking made 1 to 3 days before arrival, for 1-2 nights, from a channel whose name contains a
     word of the header vocabulary (`Booking.com`, `Walk-in`, `Check-in`, `Totale`), looks to the
     table finder like the header of a second table: the table ends on the previous row. In the
     isolation documents `B57` / `B58` only 4 records of 12 are read; the controls (same booking
     made 20 days ahead, or through an agency) are read whole. These are last-minute OTA bookings,
     the most ordinary rows of a booking export. In the six-column layout the benchmark found it in
     they are not automatic only because that layout has no status and no number of rooms (see P1);
     the manual matching screen reads the same, shortened, table.
2. **Two plausible columns, one chosen without asking.** `Ore previste` / `Ore previste (rev.)`
   (`L25`), `Imponibile` / `Imponibile (rettificato)` (`C42`), `Imponibile 22%` / `Imponibile 10%`
   (`CO04`): the first is taken with HIGH confidence and the other ignored. In the VAT register the
   net amount of every 10% invoice disappears.
3. **A column silently left out because another one satisfied the requirement.** `Ore prog.` is
   not recognised as planned hours; the file has actual hours too, so it ends READY with half of
   its hours (`L07`). The same unknown header in files without a second hours column ends safely
   in a question or in manual matching.
4. **Personal data shown or sent.** A column of names under a header NINFA does not know (`Addetto`)
   is shown with example values (3 names reach the answer to the browser, 4 the evidence a model
   would see); payroll uploaded on the costs card shows 3 names (6 in the model evidence) because
   the person-name rule is by header in the costs flow; a roster whose headers are swapped
   (`Reparto` holds names) turns the names into "departments" and lists them in the question
   (6 names). Altogether 12 personal values in 3 documents reach the browser and 10 in 2 documents
   the model evidence. Nothing is stored, but the rule "a name never leaves" does not hold when
   the header is unfamiliar.

### P1 - a valid file is blocked or sent to manual matching (26 documents)

- **Bookings: not one export with just the six business facts can be automatic.** The importer also
  requires a status and a number of rooms (from a column, or a value the person chooses) and V3.0
  has no question for them, so such files always end in the manual screen. Of 80 bookings documents
  5 were automatic. (The corpus gives most bookings a `Stato` and a `Camere` column, as a PMS does;
  the ones without are marked "needs a person" in the truth and are *not* counted as errors.)
- **Aliases and shapes not recognised**, by the number of documents they block or slow down: the
  table in section 10 lists every header. Among those the brief named: `Ore prog.`, `Amount excl.
  VAT`, `Ref.`, `Centro operativo`; and further `Imp. cam.`, `Res #`, `Bkd`, `Src`, `Eff.`/`Prev.`
  (when the title carries the word "ore"), `Numero`, `Item`, `Intestatario`.
- **Dates written with a weekday or a month name** (`ven 23/10/2026`, `19-Oct-2026`) make the
  column "not a date": a daily roster with `lun 19/10/2026` is refused as a *weekly summary*.
- **Hours with their unit** (`8 h`, `7,5 ore`) are not hours.
- **A two-level header with a single group** (`Ore` over `Previste` / `Effettive`; `Importi` over
  three columns) is read as one level.
- **No kind of data at all** for terse exports (`Res #`, `Bkd`, `Arr`, `Dep`, `Src`, `Tot`) and for
  English Airbnb-style headers: the person is asked "what kind of data is this?" about a file that
  is plainly a booking list.

### P2 - needless friction (84 documents have nothing worse)

117 questions were asked that the truth does not need, in 94 documents (80% of all questions asked).
Where they come from:

- **The channel column is only "fairly sure"** (MEDIUM), so one confirmation is asked on almost
  every bookings file (47 of the 117).
- **Words of an ordinary hotel vocabulary are unknown**: `Ristorante`, `Ricevimento`, `Portineria`,
  `Governante`, `Barista`, `Manutentore`, and the abbreviations `HK`, `HSKP`, `REC`, `FO`, `F&B`
  (24 occurrences) - and, in cost registers, the category `Colazioni` (9 files, one of the eight
categories the brief lists).
- `COLUMN_MEANING` confirmations on `H previste`, `Ore pian.`, `Ore eff.`, `Ore prev.`.
- A "which department are all these rows?" question for a file that has a department column
  (`Centro operativo`).

### P3 - edge cases

None worth a separate line: the only P3 finding is the missing question of `L25`, already counted
under P0.

### Questions

All but one necessary question were asked (96%); the missing one is the choice between `Ore previste`
and `Ore previste (rev.)`. A conversation (the truth answering round after round) reached an
automatic import in 94% of the documents that needed one, with the right reading in 92%; the average
is one round. It ends unresolved when the system asks something the document cannot answer
(`DOMAIN`, `DEPARTMENT_ROWS`, `AMOUNT_BASIS` on an amount that says it is net).

## 12. Recommendation

**SMART IMPORT V3 DETERMINISTIC - HARDENING REQUIRED**

The bar set for "robust" was: no false automation, 100% correctness of what is automated, 100% of
personal columns left out, kind of data and header at least 98%, precision at least 99%, recall at
least 95%, safe fallback 100%. Header accuracy (99.1%), recall (96.1%) and sheet selection pass;
domain accuracy (97.5%), precision (98.99%, just under), safe fallback (96.6%), personal columns
(99.1%), zero-question correctness (91.4%) and false automation (2.1%) do not.

The weakest points, in the order the benchmark ranks them:

1. a table must never end early without saying so (note lines, header-vocabulary words in a row);
2. two plausible candidates for one required fact must be asked about, never chosen;
3. a required fact has to be accounted for before the import is offered as automatic (an unknown
   alias must not disappear because a sibling column satisfied the requirement);
4. personal data must be recognised by what the values look like, not only by the header;
5. bookings need a way to supply status and rooms, or the zero-question path does not exist;
6. aliases, weekday/month-name dates and hour units (the table in section 10).

The same corpus is meant to be rerun, unchanged, for the comparison "deterministic" against
"deterministic + assistant".

## 13. Method, limits, and what changed in the truth

**How the truth was made.** It was written by hand next to each document, from what was put into it,
and the scorer only sees it as plain JSON. `corpus.validate()` checks the truth against the files
with readers that are not Smart Import's. The corpus is synthetic: names are invented, e-mail
addresses are on `example.org`, telephone numbers use a block starting `000`, tax codes use a month
letter that does not exist.

**What is measured.** The first answer to a first upload, as `UnderstandingService.understand`
produces it (the call behind `/import-understanding`), with no database and no assistant; then the
conversation, the same call with the truth's answers; a probe that uploads the corpus on another
card; and a probe that records what a model *would* be shown (a stand-in that returns an empty
answer and sends nothing anywhere). The work dates of a day grid are read from the table the
importers would read; the order of text dates and the decimal mark are the ones the import path
resolves. The values of the rows themselves (the dry run) need a database and are **not**
measured.

**Limits.** One author wrote the corpus and the truth; judgement calls are marked `tolerated` and
explained in the document's note. The mix of the corpus (how many documents have a last-minute
booking from Booking.com, how many use `Ristorante`) is a choice: the figures say what happens on
*this* corpus, not how often it happens in hotels. Time is the in-process call, without HTTP or
database; memory is the peak of Python allocations only.

**Changes to the truth after the first run** (all were mistakes or over-assertions of the benchmark,
none was made because Smart Import disagreed; every case where it disagreed with a defensible truth
was kept):

- the first bookings were drawn without a status and a number of rooms, so every one ended in
  manual matching - the importer's own contract; most now carry both, the others are "needs a
  person";
- the default roster used `Ristorante`, which made nearly every staff file ask about it; the
  default departments are now unambiguous and the vocabulary is tested by dedicated cases;
- `Ore da contratto` is contractual, not necessarily planned, hours: now "do not claim it";
- two documents whose totals do not add up are `WARN` (a warning is an acceptable answer, as the
  brief says "warning/blocco"), not "never automatic";
- a table marked "ESEMPIO ... NON MODIFICARE" above the real one: choosing the real one is fine;
- two fixtures named their sheet after the department the title states; the side blocks of two
  fixtures overwrote a column; a header row of two levels was missing in one truth;
- the period of a grid is checked on the dates the importer would read, not on a summary field;
- when the truth needs a table to be chosen, header and boundary are judged after the choice;
- sub-total / note line counts are informational, not part of "table boundary".


## Appendix A - every document with a finding

**`L32_grid_generic_day_columns`** - DOMAIN_WRONG (P2)
- card: labor - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected labor, detected other (LOW)
- mapping expected: -
- mapping observed: department <- column 'Reparto' [HIGH]
- questions expected: none - asked: none
- confidence: kind LOW; fields 1 HIGH
- why: level MANUAL; read: role<-Reparto[HIGH]; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as other (None/LOW)

**`L62_neg_swapped_header_labels`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: -
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: DEPARTMENT_ROWS
- confidence: kind HIGH; fields 3 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.747, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: DEPARTMENT_ROWS
  - QUESTION_UNNECESSARY [P2]: DEPARTMENT_ROWS could have been avoided

**`B36_two_level_header`** - FIELD_MISSED (P2)
- card: bookings - truth says: READY - NINFA: READY (automatic)
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice'; booked_at <- column 'Data prenotazione'; check_in <- column 'Soggiorno / Arrivo'; check_out <- column 'Soggiorno / Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importi / Camere'; total_revenue <- column 'Importi / Totale'; status <- column 'Stato'; rooms <- column 'N. camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Soggiorno - Arrivo' [HIGH]; check_out <- column 'Soggiorno - Partenza' [HIGH]; room_revenue <- column 'Importi - Camere' [HIGH]; rooms <- column 'N. camere' [HIGH]; source_record_id <- column 'Codice' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 8 HIGH
- why: level READY; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.376, LABOR=0.0); read: source_record_id<-Codice[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Soggiorno - Arrivo[HIGH], check_out<-Soggiorno - Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importi - Camere[HIGH], status<-Stato[HIGH], rooms<-N. camere[HIGH]
  - FIELD_MISSED [P2]: total_revenue not recognised

**`B44_office_airbnb_style_export_no_channel_column`** - FIELD_MISSED (P2)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (MEDIUM)
- mapping expected: source_record_id <- column 'Confirmation code'; status <- column 'Status'; check_in <- column 'Start date'; check_out <- column 'End date'; booked_at <- column 'Booked'; room_revenue <- column 'Earnings'
- mapping observed: booked_at <- column 'Booked' [HIGH]; check_in <- column 'Start date' [HIGH]; check_out <- column 'End date' [HIGH]; source_record_id <- column 'Confirmation code' [HIGH]; status <- column 'Status' [HIGH]
- questions expected: none - asked: none
- confidence: kind MEDIUM; fields 5 HIGH
- why: level MANUAL; kind BOOKINGS/MEDIUM (BOOKINGS=0.512, LABOR=0.253, COSTS=0.164); read: source_record_id<-Confirmation code[HIGH], status<-Status[HIGH], check_in<-Start date[HIGH], check_out<-End date[HIGH], booked_at<-Booked[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P2]: room_revenue not recognised

**`B51_neg_occupancy_calendar_not_bookings`** - DOMAIN_WRONG (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected labor (MEDIUM)
- mapping expected: -
- mapping observed: room_type <- column 'Camera' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind MEDIUM; fields 1 HIGH
- why: level MANUAL; kind LABOR/MEDIUM (LABOR=0.507, BOOKINGS=0.21, COSTS=0.0); read: room_type<-Camera[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as labor (LABOR/MEDIUM)

**`BO02_arrivals_by_day_sections_no_ids`** - DOMAIN_WRONG (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected bookings, detected other (LOW)
- mapping expected: -
- mapping observed: channel <- column 'Provenienza' [HIGH]
- questions expected: none - asked: none
- confidence: kind LOW; fields 1 HIGH
- why: level MANUAL; read: channel<-Provenienza[HIGH]; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as other (None/LOW)

**`BO04_front_desk_arrivals_list_no_booking_date`** - FIELD_MISSED (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (MEDIUM)
- mapping expected: check_in <- column 'Dal'; check_out <- column 'Al'; channel <- column 'Provenienza'; room_revenue <- column 'Tot. €'
- mapping observed: channel <- column 'Provenienza' [HIGH]; check_in <- column 'Dal' [HIGH]; check_out <- column 'Al' [HIGH]; rooms <- column 'Camere' [HIGH]
- questions expected: none - asked: none
- confidence: kind MEDIUM; fields 4 HIGH
- why: level MANUAL; kind BOOKINGS/MEDIUM (BOOKINGS=0.59, COSTS=0.048, LABOR=0.0); read: rooms<-Camere[HIGH], check_in<-Dal[HIGH], check_out<-Al[HIGH], channel<-Provenienza[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P2]: room_revenue not recognised

**`C17_everyday_category_words_luce_acqua_gas`** - FIELD_MISSED (P2)
- card: costs - truth says: READY - NINFA: READY (automatic)
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Voce'; net_amount <- column 'Netto'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Netto' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH
- why: level READY; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Netto[HIGH]
  - FIELD_MISSED [P2]: cost_category not recognised

**`C33_credit_notes_negative_amounts`** - FIELD_MISSED (P2)
- card: costs - truth says: READY - NINFA: READY (automatic)
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; document_type <- column 'Tipo'; net_amount <- column 'Imponibile'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH
- why: level READY; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH]
  - FIELD_MISSED [P2]: document_type not recognised

**`CO02_payment_schedule_not_a_register`** - FIELD_MISSED (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected costs, detected costs (MEDIUM)
- mapping expected: supplier_name <- column 'Fornitore'; invoice_number <- column 'N. fattura'; due_date <- column 'Scadenza'; invoice_gross_amount <- column 'Importo da pagare'
- mapping observed: due_date <- column 'Scadenza' [HIGH]; invoice_number <- column 'N. fattura' [HIGH]; net_amount <- column 'Importo da pagare' [MEDIUM]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind MEDIUM; fields 3 HIGH, 1 MEDIUM
- why: level MANUAL; kind COSTS/MEDIUM (COSTS=0.54, BOOKINGS=0.385, LABOR=0.253); read: supplier_name<-Fornitore[HIGH], invoice_number<-N. fattura[HIGH], due_date<-Scadenza[HIGH], line_total<-Importo da pagare[MEDIUM]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P2]: invoice_gross_amount not recognised

## Appendix B - the corpus

| Document | Card | Truth says | NINFA | Tags |
|---|---|---|---|---|
| `L01_csv_basic` | labor | READY | READY | - |
| `L02_xlsx_giorno_area` | labor | READY | READY | office |
| `L03_alias_settore_pianificate_lavorate` | labor | READY | READY | - |
| `L04_alias_dept_hprev_consuntivo` | labor | READY | READY | - |
| `L05_english_planned_actual` | labor | READY | READY | - |
| `L06_english_scheduled_worked` | labor | READY | READY | - |
| `L07_reparto_slash_mansione_ore_prog` | labor | READY | READY | - |
| `L08_reparto_o_mansione_with_hourly_rate` | labor | READY | READY | - |
| `L09_centro_operativo` | labor | READY | READY | - |
| `L10_only_planned_hours` | labor | READY | READY | - |
| `L11_only_actual_hours` | labor | READY | READY | - |
| `L12_reordered_with_junk_columns` | labor | READY | READY | office |
| `L13_title_block_before_table` | labor | READY | READY | - |
| `L14_summary_block_before_table` | labor | READY | READY | - |
| `L15_summary_block_after_table` | labor | READY | READY | - |
| `L16_total_row_correct` | labor | READY | READY | - |
| `L17_subtotals_per_department` | labor | READY | READY | - |
| `L18_sheet_per_department` | labor | READY | READY | - |
| `L19_title_names_the_department` | labor | READY | ASK | - |
| `L20_department_as_section_lines` | labor | READY | READY | - |
| `L21_sections_with_totals_and_notes` | labor | READY | READY | office |
| `L22_two_level_header` | labor | READY | READY | - |
| `L23_two_level_header_hours_over_planned_actual` | labor | READY | READY | office |
| `L24_duplicate_ore_columns` | labor | ASK | ASK | - |
| `L25_near_duplicate_hours_headers` | labor | ASK | ASK | - |
| `L26_grid_real_dates_basis_stated` | labor | READY | READY | - |
| `L27_grid_real_dates_basis_unstated` | labor | ASK | ASK | - |
| `L28_grid_weekdays_period_in_title` | labor | READY | READY | - |
| `L29_grid_three_weekdays_period_in_title` | labor | READY | READY | - |
| `L30_grid_weekdays_week_number_only` | labor | ASK | ASK | - |
| `L31_grid_weekdays_without_period` | labor | ASK | ASK | negative |
| `L32_grid_generic_day_columns` | labor | NOT_AUTOMATIC | MANUAL | negative |
| `L33_weekly_summary_without_days` | labor | REJECT | BLOCKED | negative |
| `L34_grid_shift_codes_not_hours` | labor | REJECT | BLOCKED | negative |
| `L35_grid_time_ranges_not_hours` | labor | REJECT | BLOCKED | negative |
| `L36_abbreviations_known` | labor | READY | ASK | - |
| `L37_abbreviation_man_is_ambiguous` | labor | ASK | ASK | - |
| `L38_unknown_department_codes` | labor | ASK | ASK | - |
| `L39_known_italian_department_words` | labor | READY | READY | - |
| `L40_vocabulary_restaurant_bar_governante` | labor | READY | READY | - |
| `L41_pii_split_name_email_phone_taxcode` | labor | READY | READY | - |
| `L42_pii_name_and_company_email` | labor | READY | READY | office |
| `L43_dates_us_provable` | labor | READY | READY | - |
| `L44_dates_ambiguous_day_month` | labor | ASK | ASK | negative |
| `L45_dates_weekday_prefix_text` | labor | READY | READY | - |
| `L46_dates_dotted_text_hours_comma` | labor | READY | READY | - |
| `L47_rates_and_costs_columns` | labor | READY | READY | - |
| `L48_two_comparable_tables_two_weeks` | labor | ASK | ASK | - |
| `L49_decoy_legend_table_before_real_one` | labor | READY | READY | - |
| `L50_hidden_draft_sheet_and_visible_sheet` | labor | READY | READY | adversarial |
| `L51_summary_sheet_first_then_detail` | labor | READY | READY | - |
| `L52_dashboard_sheet_and_data_sheet` | labor | READY | READY | office |
| `L53_header_on_row_nine_after_long_preamble` | labor | READY | READY | office |
| `L54_office_weekly_roster_final` | labor | READY | READY | office |
| `L55_office_monthly_hours_report` | labor | READY | READY | office |
| `L56_office_front_desk_roster_csv` | labor | READY | ASK | office |
| `L57_office_kitchen_and_restaurant_two_sheets` | labor | READY | READY | office |
| `L58_office_names_in_two_columns_and_comments` | labor | READY | READY | office |
| `L59_neg_no_hours_at_all` | labor | REJECT | MANUAL | negative |
| `L60_neg_totals_by_person_only` | labor | REJECT | BLOCKED | negative |
| `L61_neg_totals_row_contradicts_rows` | labor | WARN | READY | negative |
| `L62_neg_swapped_header_labels` | labor | NOT_AUTOMATIC | ASK | negative |
| `L63_neg_mixed_date_formats` | labor | NOT_AUTOMATIC | BLOCKED | negative |
| `L64_neg_headers_only_no_rows` | labor | REJECT | BLOCKED | negative |
| `L65_neg_restaurant_menu_other_domain` | labor | REJECT | MANUAL | negative |
| `L66_neg_bookings_file_on_staff_card` | labor | NOT_AUTOMATIC | MANUAL | negative |
| `L67_adv_prompt_injection_in_cells` | labor | READY | READY | adversarial, pii |
| `L68_adv_formulas_html_and_unicode` | labor | READY | READY | adversarial |
| `L69_adv_very_long_cell_and_odd_headers` | labor | READY | READY | adversarial |
| `L70_adv_example_table_before_real_table` | labor | READY | READY | adversarial |
| `L71_adv_total_word_inside_a_department` | labor | ASK | ASK | adversarial |
| `L72_large_three_months_roster` | labor | READY | READY | large |
| `LO01_reception_roster_bare_ore_title_department` | labor | ASK | ASK | office |
| `LO02_payroll_monthly_summary_by_qualifica` | labor | REJECT | BLOCKED | office, negative |
| `LO03_clock_in_out_times_no_hours` | labor | REJECT | MANUAL | office, negative |
| `LO04_weekday_name_and_date_in_two_columns` | labor | READY | READY | office |
| `LO05_future_days_have_no_actual_hours_yet` | labor | READY | READY | office |
| `LO06_job_titles_in_qualifica_column` | labor | READY | READY | office |
| `LO07_department_in_a_label_value_block` | labor | READY | READY | office |
| `LO08_one_sheet_per_week_sett43_sett44` | labor | READY | READY | office |
| `LO09_legend_block_drawn_beside_the_table` | labor | READY | READY | office |
| `LO10_header_repeated_in_every_department_block` | labor | NOT_AUTOMATIC | ASK | office, negative |
| `LO11_department_cells_merged_down_the_column` | labor | READY | READY | office |
| `LO12_blank_row_between_every_record` | labor | READY | READY | office |
| `LO13_hours_written_with_a_unit` | labor | READY | READY | office |
| `LO14_header_cells_with_line_breaks` | labor | READY | READY | office |
| `LO15_abbreviated_department_header_and_codes` | labor | READY | ASK | office |
| `LO16_extra_numeric_columns_overtime_leave` | labor | READY | READY | office |
| `B01_csv_italian_canonical` | bookings | READY | READY | - |
| `B02_npren_prenotato_il_dal_al` | bookings | READY | READY | - |
| `B03_english_booking_id_created_source` | bookings | NOT_AUTOMATIC | MANUAL | - |
| `B04_english_reservation_id_creation_date` | bookings | READY | READY | - |
| `B05_confirmation_booked_at_accommodation` | bookings | NOT_AUTOMATIC | MANUAL | - |
| `B06_ref_portale_totale_soggiorno` | bookings | READY | READY | - |
| `B07_room_revenue_and_total_stay_both` | bookings | READY | READY | - |
| `B08_abbreviated_headers` | bookings | READY | READY | - |
| `B09_mixed_italian_english_headers` | bookings | READY | READY | office |
| `B10_guest_name_email_phone_notes` | bookings | READY | READY | - |
| `B11_guest_column_holds_names_not_a_count` | bookings | READY | READY | - |
| `B12_guests_count_column_and_guest_name` | bookings | READY | READY | - |
| `B13_pax_and_num_ospiti` | bookings | READY | READY | - |
| `B14_booker_and_guest_names_two_columns` | bookings | READY | ASK | - |
| `B15_title_before_table` | bookings | READY | READY | - |
| `B16_notes_below_the_table` | bookings | READY | READY | - |
| `B17_summary_block_before_table` | bookings | READY | READY | - |
| `B18_totals_row_and_channel_subtotals` | bookings | READY | READY | - |
| `B19_dashboard_bookings_and_legend_sheets` | bookings | READY | READY | - |
| `B20_sheet_per_month_same_columns` | bookings | READY | READY | - |
| `B21_two_tables_confirmed_and_cancelled` | bookings | ASK | ASK | - |
| `B22_status_and_cancellation_date` | bookings | READY | READY | - |
| `B23_status_modificata_is_ambiguous` | bookings | ASK | ASK | - |
| `B24_channels_direct_phone_email_walkin` | bookings | READY | READY | - |
| `B25_ota_channels_with_commission_columns` | bookings | READY | READY | - |
| `B26_amounts_thousands_dot_comma_decimal` | bookings | READY | READY | - |
| `B27_amounts_point_decimal_csv` | bookings | READY | READY | - |
| `B28_amounts_with_euro_sign_text` | bookings | READY | READY | - |
| `B29_amounts_excel_currency_format` | bookings | READY | READY | - |
| `B30_dates_text_italian` | bookings | READY | READY | - |
| `B31_dates_us_provable_csv` | bookings | READY | READY | - |
| `B32_dates_ambiguous_day_month` | bookings | ASK | ASK | negative |
| `B33_dates_dotted_and_day_month_name` | bookings | READY | READY | - |
| `B34_dates_day_month_name_text` | bookings | READY | READY | - |
| `B35_booking_timestamp_with_time` | bookings | READY | READY | - |
| `B36_two_level_header` | bookings | READY | READY | - |
| `B37_duplicate_date_columns` | bookings | NOT_AUTOMATIC | MANUAL | negative |
| `B38_reordered_columns_with_junk` | bookings | READY | READY | - |
| `B39_ids_with_leading_zeros_and_numeric` | bookings | READY | READY | - |
| `B40_office_pms_export_colored_header` | bookings | READY | READY | office |
| `B41_office_channel_manager_extract` | bookings | READY | ASK | office |
| `B42_office_front_desk_monthly_report` | bookings | READY | ASK | office |
| `B43_office_repeated_header_every_page` | bookings | READY | READY | office, adversarial |
| `B44_office_airbnb_style_export_no_channel_column` | bookings | NOT_AUTOMATIC | MANUAL | office, negative |
| `B45_neg_missing_checkout` | bookings | REJECT | MANUAL | negative |
| `B46_neg_missing_booking_date` | bookings | REJECT | MANUAL | negative |
| `B47_neg_missing_revenue` | bookings | REJECT | MANUAL | negative |
| `B48_neg_missing_channel` | bookings | NOT_AUTOMATIC | MANUAL | negative |
| `B49_neg_nights_instead_of_checkout` | bookings | REJECT | MANUAL | negative |
| `B50_neg_arrival_and_departure_swapped` | bookings | NOT_AUTOMATIC | ASK | negative |
| `B51_neg_occupancy_calendar_not_bookings` | bookings | REJECT | MANUAL | negative |
| `B52_neg_only_a_dashboard` | bookings | REJECT | BLOCKED | negative |
| `B53_neg_staff_file_on_bookings_card` | bookings | NOT_AUTOMATIC | MANUAL | negative |
| `B54_neg_costs_register_on_bookings_card` | bookings | NOT_AUTOMATIC | MANUAL | negative |
| `B55_neg_checkout_before_arrival_rows` | bookings | NOT_AUTOMATIC | ASK | negative |
| `B56_isolation_control_booking_com_made_well_ahead` | bookings | NOT_AUTOMATIC | MANUAL | isolation |
| `B57_isolation_last_minute_booking_com` | bookings | NOT_AUTOMATIC | MANUAL | isolation |
| `B58_isolation_last_minute_walk_in` | bookings | NOT_AUTOMATIC | MANUAL | isolation |
| `B59_isolation_last_minute_agency` | bookings | NOT_AUTOMATIC | MANUAL | isolation |
| `B60_adv_hidden_sheet_with_older_bookings` | bookings | READY | READY | adversarial |
| `B61_adv_instructions_in_guest_notes` | bookings | READY | READY | adversarial |
| `B62_adv_formulas_and_html_in_cells` | bookings | READY | READY | adversarial |
| `B63_adv_total_word_in_a_notes_column` | bookings | READY | READY | adversarial |
| `B64_adv_near_identical_date_headers` | bookings | NOT_AUTOMATIC | ASK | adversarial |
| `B65_adv_very_long_cells_and_unicode` | bookings | READY | READY | adversarial |
| `B66_large_year_of_bookings` | bookings | READY | READY | large |
| `BO01_channel_written_as_codes` | bookings | READY | ASK | office |
| `BO02_arrivals_by_day_sections_no_ids` | bookings | REJECT | MANUAL | office, negative |
| `BO03_channel_manager_abbreviations` | bookings | READY | ASK | office |
| `BO04_front_desk_arrivals_list_no_booking_date` | bookings | REJECT | MANUAL | office, negative |
| `BO05_kpi_block_beside_the_table` | bookings | READY | READY | office |
| `BO06_table_starts_in_column_c_frozen_panes` | bookings | READY | READY | office |
| `BO07_weekday_prefixed_dates` | bookings | READY | READY | office |
| `BO08_room_and_breakfast_revenue_columns` | bookings | READY | READY | office |
| `BO09_status_written_as_ok_canc_ns` | bookings | READY | ASK | office |
| `BO10_one_sheet_per_week` | bookings | READY | READY | office |
| `BO11_header_cells_with_line_breaks` | bookings | READY | READY | office |
| `BO12_channel_merged_down_the_column` | bookings | READY | READY | office |
| `BO13_blank_row_between_every_record` | bookings | READY | READY | office |
| `BO14_two_months_side_by_side` | bookings | NOT_AUTOMATIC | MANUAL | office, negative |
| `C01_complete_register_consistent` | costs | READY | READY | - |
| `C02_english_amount_excl_vat` | costs | READY | READY | - |
| `C03_totale_netto_imposta_totale` | costs | READY | READY | - |
| `C04_imponibile_iva_lordo` | costs | READY | READY | - |
| `C05_net_vat_gross_amount_english` | costs | READY | READY | - |
| `C06_netto_only` | costs | READY | READY | - |
| `C07_imponibile_only` | costs | READY | READY | - |
| `C08_net_vat_total_do_not_add_up` | costs | WARN | READY | negative |
| `C09_single_amount_column_importo` | costs | ASK | ASK | - |
| `C10_only_totale_may_be_gross` | costs | ASK | MANUAL | negative |
| `C11_only_gross_stated_vat_included` | costs | NOT_AUTOMATIC | BLOCKED | negative |
| `C12_neg_without_document_number` | costs | REJECT | MANUAL | negative |
| `C13_neg_without_description` | costs | REJECT | MANUAL | negative |
| `C14_neg_without_supplier` | costs | REJECT | MANUAL | negative |
| `C15_neg_without_date` | costs | REJECT | MANUAL | negative |
| `C16_eight_known_categories` | costs | READY | READY | - |
| `C17_everyday_category_words_luce_acqua_gas` | costs | READY | READY | - |
| `C18_unknown_category_words` | costs | ASK | ASK | - |
| `C19_no_category_column` | costs | READY | READY | - |
| `C20_title_before_table` | costs | READY | READY | office |
| `C21_total_row_correct` | costs | READY | READY | - |
| `C22_summary_block_before_table` | costs | READY | READY | - |
| `C23_subtotals_per_category` | costs | READY | READY | - |
| `C24_summary_sheet_and_register_sheet` | costs | READY | READY | - |
| `C25_supplier_directory_sheet_and_invoices_sheet` | costs | READY | READY | - |
| `C26_sheet_per_month_same_columns` | costs | READY | READY | - |
| `C27_dates_text_italian` | costs | READY | READY | - |
| `C28_dates_iso_csv` | costs | READY | READY | - |
| `C29_dates_ambiguous_us_or_italian` | costs | ASK | ASK | negative |
| `C30_amounts_italian_thousands` | costs | READY | READY | - |
| `C31_amounts_us_thousands_csv` | costs | READY | READY | - |
| `C32_amounts_euro_sign_text` | costs | READY | READY | - |
| `C33_credit_notes_negative_amounts` | costs | READY | READY | - |
| `C34_currency_symbol_and_codes` | costs | READY | READY | - |
| `C35_no_currency_column` | costs | READY | READY | - |
| `C36_document_number_styles` | costs | READY | READY | - |
| `C37_vat_number_and_due_date_columns` | costs | READY | READY | - |
| `C38_several_lines_per_invoice` | costs | READY | READY | - |
| `C39_total_word_inside_a_description` | costs | READY | READY | adversarial |
| `C40_two_level_header_importi` | costs | READY | READY | - |
| `C41_duplicate_importo_columns` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C42_near_identical_net_headers` | costs | NOT_AUTOMATIC | MANUAL | adversarial |
| `C43_reordered_with_junk_columns` | costs | READY | READY | - |
| `C44_office_accounting_export_header_on_row_five` | costs | READY | READY | office |
| `C45_office_cost_ledger_csv_semicolon` | costs | READY | READY | office |
| `C46_office_manual_expense_sheet` | costs | READY | ASK | office |
| `C47_office_supplier_invoices_with_notes` | costs | READY | READY | office |
| `C48_neg_bank_statement` | costs | REJECT | MANUAL | negative |
| `C49_neg_payroll_with_names` | costs | REJECT | BLOCKED | negative |
| `C50_neg_staff_roster_on_costs_card` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C51_neg_bookings_on_costs_card` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C52_neg_empty_register` | costs | REJECT | BLOCKED | negative |
| `C53_neg_mixed_date_formats` | costs | NOT_AUTOMATIC | BLOCKED | negative |
| `C54_neg_costs_and_revenues_two_tables` | costs | ASK | ASK | negative |
| `C55_adv_hidden_sheet_with_other_invoices` | costs | READY | READY | adversarial |
| `C56_adv_instructions_in_descriptions` | costs | READY | READY | adversarial |
| `C57_adv_formulas_html_and_unicode` | costs | READY | READY | adversarial |
| `C58_adv_very_long_description_cell` | costs | READY | READY | adversarial |
| `C59_large_year_of_invoices` | costs | READY | READY | large |
| `CO01_protocol_number_and_supplier_document_number` | costs | READY | READY | office |
| `CO02_payment_schedule_not_a_register` | costs | REJECT | MANUAL | office, negative |
| `CO03_cost_centre_and_department_columns` | costs | READY | READY | office |
| `CO04_vat_register_two_rates_two_dates` | costs | NOT_AUTOMATIC | MANUAL | office, negative |
| `CO05_cash_book_not_invoices` | costs | REJECT | MANUAL | office, negative |
| `CO06_utilities_summary_without_number_or_supplier` | costs | REJECT | MANUAL | office, negative |
| `CO07_supplier_written_as_section_lines` | costs | REJECT | MANUAL | office, negative |
| `CO08_supplier_cells_merged_down_the_column` | costs | READY | READY | office |
| `CO09_amounts_with_eur_suffix_text` | costs | READY | READY | office |
| `CO10_header_cells_with_line_breaks` | costs | READY | READY | office |
| `CO11_blank_row_between_every_record` | costs | READY | READY | office |
| `CO12_attachment_and_approval_columns` | costs | READY | READY | office |
| `CO13_category_by_month_matrix_not_a_register` | costs | REJECT | MANUAL | office, negative |
