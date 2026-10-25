# Smart Import V3 - Intelligence Benchmark V1

Baseline: `main` = `48a1a656edc98b15665153c0d7322411f1a46988` (Smart Import V3.0, merged). Assistant: **off** - IMPORT_UNDERSTANDING_PROVIDER=unconfigured; no model was called. Run on 240 synthetic documents, 2026-10-25.

Rerun with one command, from `services/api`: `python -m tests.benchmarks.smart_import_v3` (console summary + JSON in `tests/benchmarks/results/` + this report). Nothing is read from or written to a database, nothing leaves the process, no model is called.

## 1. Result

Targets are the ones the benchmark was asked to compare against; nothing was changed to reach them.

| Metric | Target | Total | Personale | Prenotazioni | Costi | Total vs target |
|---|---|---|---|---|---|---|
| False automation rate | <= 0% | 2.1% (5/240) | 2.3% (2/88) | 1.2% (1/80) | 2.8% (2/72) | **missed** |
| Zero-question correctness | >= 100% | 91.4% (74/81) | 95.6% (43/45) | 60.0% (3/5) | 90.3% (28/31) | **missed** |
| Personal columns left out | >= 100% | 99.1% (107/108) | 98.9% (93/94) | 100.0% (13/13) | 100.0% (1/1) | **missed** |
| Domain accuracy | >= 98% | 97.5% (232/238) | 97.7% (85/87) | 95.0% (76/80) | 100.0% (71/71) | **missed** |
| Header accuracy | >= 98% | 99.1% (233/235) | 98.8% (85/86) | 100.0% (78/78) | 98.6% (70/71) | met |
| Required-field precision | >= 99% | 99.0% (981/991) | 99.6% (279/280) | 99.0% (410/414) | 98.3% (292/297) | **missed** |
| Required-field recall | >= 95% | 96.1% (981/1021) | 96.5% (279/289) | 95.3% (410/430) | 96.7% (292/302) | met |
| Safe fallback (documents to refuse) | >= 100% | 96.6% (56/58) | 100.0% (15/15) | 100.0% (23/23) | 90.0% (18/20) | **missed** |

**False automation: 5 of 240 documents (2.1%)** - offered as automatic (a summary and one button) while the reading differs from the truth in a business-critical field, or while the document should never have been automatic. They are listed in section 3.

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

| Document | Card | Truth says | What differs | What NINFA decided |
|---|---|---|---|---|
| `L07_reparto_slash_mansione_ore_prog` | labor | READY | planned_hours missed | level READY; kind LABOR/HIGH (LABOR=0.94, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto / Mansione[HIGH], actual_hours<-Ore effettive[HIGH] |
| `L25_near_duplicate_hours_headers` | labor | ASK | automatic where ASK expected; planned_hours guessed | level READY; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH] |
| `B43_office_repeated_header_every_page` | bookings | READY | table boundary wrong | level READY; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH] |
| `C42_near_identical_net_headers` | costs | NOT_AUTOMATIC | automatic where NOT_AUTOMATIC expected; net_amount guessed | level READY; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH] |
| `CO04_vat_register_two_rates_two_dates` | costs | NOT_AUTOMATIC | automatic where NOT_AUTOMATIC expected; net_amount guessed | level READY; kind COSTS/HIGH (COSTS=0.82, LABOR=0.253, BOOKINGS=0.18); read: invoice_date<-Data doc.[HIGH], invoice_number<-N. doc.[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile 22%[HIGH], invoice_tax_amount<-IVA 22%[HIGH], invoice_gross_amount<-Totale doc.[MEDIUM] |

## 4. Zero-question audit

81 documents ended READY; 81 of them with no question and no blocker (automatic). Every one is listed.

| Document | Card | Totally correct? | What was wrong |
|---|---|---|---|
| `B25_ota_channels_with_commission_columns` | bookings | **NOT correct** | FIELD_MISSED: commission_rate not recognised |
| `B43_office_repeated_header_every_page` | bookings | **NOT correct** | TABLE_BOUNDARY_WRONG: 8 records read, 24 in the document; FALSE_ZERO_QUESTION: offered as automatic with: table boundary wrong |
| `C17_everyday_category_words_luce_acqua_gas` | costs | **NOT correct** | FIELD_MISSED: cost_category not recognised |
| `C42_near_identical_net_headers` | costs | **NOT correct** | FIELD_WRONG: net_amount decided without asking (column 'Imponibile' [HIGH]); the document does not say; UNSAFE_IMPORT: offered as automatic, but the document needs a person |
| `CO04_vat_register_two_rates_two_dates` | costs | **NOT correct** | FIELD_WRONG: net_amount decided without asking (column 'Imponibile 22%' [HIGH]); the document does not say; UNSAFE_IMPORT: offered as automatic, but the document needs a person |
| `L07_reparto_slash_mansione_ore_prog` | labor | **NOT correct** | FIELD_MISSED: planned_hours not recognised; FALSE_ZERO_QUESTION: offered as automatic with: planned_hours missed |
| `L25_near_duplicate_hours_headers` | labor | **NOT correct** | FIELD_WRONG: planned_hours decided without asking (column 'Ore previste' [HIGH]); the document does not say; FALSE_ZERO_QUESTION: offered as automatic, but the document needs COLUMN_MEANING; QUESTION_MISSING: COLUMN_MEANING was not asked (READY) |
| `B18_totals_row_and_channel_subtotals` | bookings | correct | - |
| `B26_amounts_thousands_dot_comma_decimal` | bookings | correct | - |
| `BO12_channel_merged_down_the_column` | bookings | correct | - |
| `C03_totale_netto_imposta_totale` | costs | correct | - |
| `C04_imponibile_iva_lordo` | costs | correct | - |
| `C06_netto_only` | costs | correct | - |
| `C08_net_vat_total_do_not_add_up` | costs | correct (contradiction shown as a warning) | - |
| `C19_no_category_column` | costs | correct | - |
| `C21_total_row_correct` | costs | correct | - |
| `C22_summary_block_before_table` | costs | correct | - |
| `C23_subtotals_per_category` | costs | correct | - |
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
| `C39_total_word_inside_a_description` | costs | correct | - |
| `C55_adv_hidden_sheet_with_other_invoices` | costs | correct | - |
| `C56_adv_instructions_in_descriptions` | costs | correct | - |
| `C57_adv_formulas_html_and_unicode` | costs | correct | - |
| `C58_adv_very_long_description_cell` | costs | correct | - |
| `CO01_protocol_number_and_supplier_document_number` | costs | correct | - |
| `CO08_supplier_cells_merged_down_the_column` | costs | correct | - |
| `CO10_header_cells_with_line_breaks` | costs | correct | - |
| `CO11_blank_row_between_every_record` | costs | correct | - |
| `L01_csv_basic` | labor | correct | - |
| `L02_xlsx_giorno_area` | labor | correct | - |
| `L03_alias_settore_pianificate_lavorate` | labor | correct | - |
| `L05_english_planned_actual` | labor | correct | - |
| `L06_english_scheduled_worked` | labor | correct | - |
| `L08_reparto_o_mansione_with_hourly_rate` | labor | correct | - |
| `L10_only_planned_hours` | labor | correct | - |
| `L11_only_actual_hours` | labor | correct | - |
| `L12_reordered_with_junk_columns` | labor | correct | - |
| `L13_title_block_before_table` | labor | correct | - |
| `L14_summary_block_before_table` | labor | correct | - |
| `L15_summary_block_after_table` | labor | correct | - |
| `L16_total_row_correct` | labor | correct | - |
| `L17_subtotals_per_department` | labor | correct | - |
| `L20_department_as_section_lines` | labor | correct | - |
| `L21_sections_with_totals_and_notes` | labor | correct | - |
| `L22_two_level_header` | labor | correct | - |
| `L26_grid_real_dates_basis_stated` | labor | correct | - |
| `L28_grid_weekdays_period_in_title` | labor | correct | - |
| `L29_grid_three_weekdays_period_in_title` | labor | correct | - |
| `L41_pii_split_name_email_phone_taxcode` | labor | correct | - |
| `L43_dates_us_provable` | labor | correct | - |
| `L46_dates_dotted_text_hours_comma` | labor | correct | - |
| `L47_rates_and_costs_columns` | labor | correct | - |
| `L49_decoy_legend_table_before_real_one` | labor | correct | - |
| `L50_hidden_draft_sheet_and_visible_sheet` | labor | correct | - |
| `L51_summary_sheet_first_then_detail` | labor | correct | - |
| `L52_dashboard_sheet_and_data_sheet` | labor | correct | - |
| `L53_header_on_row_nine_after_long_preamble` | labor | correct | - |
| `L55_office_monthly_hours_report` | labor | correct | - |
| `L61_neg_totals_row_contradicts_rows` | labor | correct (contradiction shown as a warning) | - |
| `L67_adv_prompt_injection_in_cells` | labor | correct | - |
| `L68_adv_formulas_html_and_unicode` | labor | correct | - |
| `L70_adv_example_table_before_real_table` | labor | correct | - |
| `L72_large_three_months_roster` | labor | correct | - |
| `LO04_weekday_name_and_date_in_two_columns` | labor | correct | - |
| `LO05_future_days_have_no_actual_hours_yet` | labor | correct | - |
| `LO08_one_sheet_per_week_sett43_sett44` | labor | correct | - |
| `LO09_legend_block_drawn_beside_the_table` | labor | correct | - |
| `LO11_department_cells_merged_down_the_column` | labor | correct | - |
| `LO12_blank_row_between_every_record` | labor | correct | - |
| `LO14_header_cells_with_line_breaks` | labor | correct | - |
| `LO16_extra_numeric_columns_overtime_leave` | labor | correct | - |

## 5. All metrics

| Metric | Total | Personale | Prenotazioni | Costi |
|---|---|---|---|---|
| Domain accuracy | 97.5% (232/238) | 97.7% (85/87) | 95.0% (76/80) | 100.0% (71/71) |
| Sheet selection accuracy (multi-sheet documents) | 100.0% (14/14) | 100.0% (6/6) | 100.0% (4/4) | 100.0% (4/4) |
| Header detection accuracy | 99.1% (233/235) | 98.8% (85/86) | 100.0% (78/78) | 98.6% (70/71) |
| Table boundary accuracy (first record + number of records) | 98.7% (232/235) | 100.0% (86/86) | 96.2% (75/78) | 100.0% (71/71) |
| Required-field precision (every claim) | 99.0% (981/991) | 99.6% (279/280) | 99.0% (410/414) | 98.3% (292/297) |
| Required-field precision (claims without a question) | 99.1% (963/972) | 99.6% (279/280) | 99.0% (394/398) | 98.6% (290/294) |
| Required-field recall | 96.1% (981/1021) | 96.5% (279/289) | 95.3% (410/430) | 96.7% (292/302) |
| Required-field recall, counting columns the person is asked about | 96.1% (981/1021) | 96.5% (279/289) | 95.3% (410/430) | 96.7% (292/302) |
| All-fields precision | 99.0% (1182/1194) | 99.6% (281/282) | 99.3% (549/553) | 98.1% (352/359) |
| All-fields recall | 96.3% (1182/1228) | 96.6% (281/291) | 96.0% (549/572) | 96.4% (352/365) |
| Personal columns left out of the import | 99.1% (107/108) | 98.9% (93/94) | 100.0% (13/13) | 100.0% (1/1) |
| Zero-question coverage | 33.8% (81/240) | 51.1% (45/88) | 6.2% (5/80) | 43.1% (31/72) |
| Zero-question correctness | 91.4% (74/81) | 95.6% (43/45) | 60.0% (3/5) | 90.3% (28/31) |
| FALSE AUTOMATION RATE (of all documents) | 2.1% (5/240) | 2.3% (2/88) | 1.2% (1/80) | 2.8% (2/72) |
| False automation, of the documents offered as automatic | 6.2% (5/81) | 4.4% (2/45) | 20.0% (1/5) | 6.5% (2/31) |
| Necessary-question recall | 96.0% (24/25) | 92.3% (12/13) | 100.0% (5/5) | 100.0% (7/7) |
| Unnecessary-question rate (of the questions asked) | 79.6% (117/147) | 62.5% (30/48) | 92.5% (62/67) | 78.1% (25/32) |
| Safe fallback (not automatic) | 96.6% (56/58) | 100.0% (15/15) | 100.0% (23/23) | 90.0% (18/20) |
| Safe fallback, strict (refusal documents ending manual or blocked) | 100.0% (29/29) | 100.0% (9/9) | 100.0% (8/8) | 100.0% (12/12) |
| Conversations that end in an automatic import | 94.3% (82/87) | 95.7% (22/23) | 95.9% (47/49) | 86.7% (13/15) |
| ...and end with the right reading | 92.0% (80/87) | 91.3% (21/23) | 93.9% (46/49) | 86.7% (13/15) |
| Documents | 240 | 88 | 80 | 72 |
| Documents with a false automation | 5 | 2 | 1 | 2 |
| Personal values found in what is sent to the browser | 12 | 9 | 0 | 3 |
| Documents with such a leak | 3 | 2 | 0 | 1 |
| Junk columns that became a field | 2 | 0 | 0 | 2 |
| Questions asked / unnecessary | 147 / 117 | 48 / 30 | 67 / 62 | 32 / 25 |
| Documents with at least one unnecessary question | 94 | 20 | 52 | 22 |
| Department words asked about that needed no question | 24 | 13 | 3 | 8 |
| Department words decided silently | 0 | 0 | 0 | 0 |
| Department words read as the wrong category | 0 | 0 | 0 | 0 |
| Automatic with a visible warning | 3 | 1 | 0 | 2 |
| Rounds of answers needed (mean) | 1.0 | 1.0 | 1.0 | 1.0 |

## 6. Questions

Necessary questions: asked 96.0% (24/25). Missing: `L25_near_duplicate_hours_headers` (COLUMN_MEANING).

Unnecessary questions by kind (every question the truth does not need or tolerate):

| Card | Kind | Questions |
|---|---|---|
| bookings | COLUMN_MEANING | 57 |
| labor | COLUMN_MEANING | 15 |
| costs | VALUE_LABELS | 11 |
| labor | VALUE_LABELS | 8 |
| costs | AMOUNT_BASIS | 6 |
| costs | DOMAIN | 5 |
| labor | DEPARTMENT_ROWS | 4 |
| bookings | DOMAIN | 4 |
| labor | DOMAIN | 3 |
| costs | COLUMN_MEANING | 3 |
| bookings | VALUE_LABELS | 1 |

The most frequent single causes (kind and column):

| Card | Question | Times |
|---|---|---|
| bookings | COLUMN_MEANING (Canale) | 39 |
| bookings | COLUMN_MEANING (Channel) | 4 |
| labor | COLUMN_MEANING (Ore eff.) | 3 |
| labor | COLUMN_MEANING (Ore pian.) | 2 |
| bookings | COLUMN_MEANING (Provenienza) | 2 |
| bookings | COLUMN_MEANING (Codice) | 2 |
| bookings | COLUMN_MEANING (Tot. €) | 2 |
| costs | AMOUNT_BASIS (Importo) | 2 |
| labor | COLUMN_MEANING (H previste) | 1 |
| labor | COLUMN_MEANING (Programmate) | 1 |
| labor | COLUMN_MEANING (Ore prev.) | 1 |
| labor | COLUMN_MEANING (Ore Prev.) | 1 |
| labor | COLUMN_MEANING (Ore Lav.) | 1 |
| labor | COLUMN_MEANING (gg) | 1 |
| labor | COLUMN_MEANING (Totale ore) | 1 |

## 7. Personal data

Personal columns left out of the import: 99.1% (107/108).
Personal values that appear in what the API sends to the browser: 12 (in 3 documents, out of 740 values checked).
What would be shown to a language model, if one were configured: 53 documents would reach it (53 calls recorded, nothing sent anywhere); personal values in that evidence: 10.

| Document | Values in the browser answer | Values in the model evidence | What happened |
|---|---|---|---|
| `L56_office_front_desk_roster_csv` | 3 | 4 | 3 personal values are in the answer sent to the browser |
| `L62_neg_swapped_header_labels` | 6 | 0 | personal column 'Reparto' became role; 6 personal values are in the answer sent to the browser |
| `C49_neg_payroll_with_names` | 3 | 6 | 3 personal values are in the answer sent to the browser |

## 8. Results by kind of data

### Personale

88 documents; levels {'READY': 45, 'ASK': 28, 'MANUAL': 7, 'BLOCKED': 8}; findings by worst severity {'P0': 4, 'P1': 5, 'P2': 17, 'P3': 0}; clean documents 62.

| Metric | Value |
|---|---|
| Domain accuracy | 97.7% (85/87) |
| Header accuracy | 98.8% (85/86) |
| Table boundary accuracy | 100.0% (86/86) |
| Required precision / recall | 99.6% (279/280) / 96.5% (279/289) |
| Zero-question coverage / correctness | 51.1% (45/88) / 95.6% (43/45) |
| False automation | 2 (2.3% (2/88)) |
| Necessary-question recall | 92.3% (12/13) |
| Unnecessary-question rate | 62.5% (30/48) |
| Safe fallback | 100.0% (15/15) |
| Wrong-card probe (uploaded on another card) | 73 documents: automatic 0, asked 'what kind of data' 73 |

### Prenotazioni

80 documents; levels {'ASK': 47, 'MANUAL': 27, 'READY': 5, 'BLOCKED': 1}; findings by worst severity {'P0': 3, 'P1': 11, 'P2': 49, 'P3': 0}; clean documents 17.

| Metric | Value |
|---|---|
| Domain accuracy | 95.0% (76/80) |
| Header accuracy | 100.0% (78/78) |
| Table boundary accuracy | 96.2% (75/78) |
| Required precision / recall | 99.0% (410/414) / 95.3% (410/430) |
| Zero-question coverage / correctness | 6.2% (5/80) / 60.0% (3/5) |
| False automation | 1 (1.2% (1/80)) |
| Necessary-question recall | 100.0% (5/5) |
| Unnecessary-question rate | 92.5% (62/67) |
| Safe fallback | 100.0% (23/23) |
| Wrong-card probe (uploaded on another card) | 57 documents: automatic 0, asked 'what kind of data' 57 |

### Costi

72 documents; levels {'ASK': 15, 'MANUAL': 24, 'READY': 31, 'BLOCKED': 2}; findings by worst severity {'P0': 3, 'P1': 10, 'P2': 18, 'P3': 0}; clean documents 41.

| Metric | Value |
|---|---|
| Domain accuracy | 100.0% (71/71) |
| Header accuracy | 98.6% (70/71) |
| Table boundary accuracy | 100.0% (71/71) |
| Required precision / recall | 98.3% (292/297) / 96.7% (292/302) |
| Zero-question coverage / correctness | 43.1% (31/72) / 90.3% (28/31) |
| False automation | 2 (2.8% (2/72)) |
| Necessary-question recall | 100.0% (7/7) |
| Unnecessary-question rate | 78.1% (25/32) |
| Safe fallback | 90.0% (18/20) |
| Wrong-card probe (uploaded on another card) | 52 documents: automatic 0, asked 'what kind of data' 52 |

## 9. Performance

Baseline only, nothing optimised. Timing is the median of 3 calls per document after a warm-up; memory is the peak of Python allocations (`tracemalloc`) of one call. Mean 124 ms, p50 100 ms, p95 168 ms, max 1686 ms per document.

|  | mean ms | p50 ms | p95 ms | max ms | peak Python memory MiB (p50 / max) | file KiB (p50 / max) |
|---|---|---|---|---|---|---|
| total | 124 | 100 | 168 | 1686 | 0.5 / 12.3 | 5.7 / 137 |
| Personale | 96 | 80 | 122 | 1122 | 0.5 / 5.0 | 5.5 / 40 |
| Prenotazioni | 158 | 138 | 189 | 1686 | 0.5 / 12.3 | 5.9 / 137 |
| Costi | 120 | 95 | 144 | 1564 | 0.6 / 10.3 | 5.9 / 120 |

## 10. Confusion report and failure modes

Findings by category - the figure in brackets is the number of documents. Every finding of every document is in Appendix A.

| Category | Total | Personale | Prenotazioni | Costi |
|---|---|---|---|---|
| DOMAIN_WRONG | 6 (6) | 2 (2) | 4 (4) | 0 (0) |
| SHEET_WRONG | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| HEADER_WRONG | 2 (2) | 1 (1) | 0 (0) | 1 (1) |
| TABLE_BOUNDARY_WRONG | 3 (3) | 0 (0) | 3 (3) | 0 (0) |
| FIELD_WRONG | 9 (8) | 1 (1) | 4 (3) | 4 (4) |
| FIELD_MISSED | 44 (31) | 10 (8) | 22 (12) | 12 (11) |
| PII_LEAK | 4 (3) | 3 (2) | 0 (0) | 1 (1) |
| QUESTION_MISSING | 1 (1) | 1 (1) | 0 (0) | 0 (0) |
| QUESTION_UNNECESSARY | 117 (94) | 30 (20) | 62 (52) | 25 (22) |
| FALSE_ZERO_QUESTION | 3 (3) | 2 (2) | 1 (1) | 0 (0) |
| UNSAFE_IMPORT | 2 (2) | 0 (0) | 0 (0) | 2 (2) |
| EXPECTED_REJECTION | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| OTHER | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

Failure modes: findings grouped by category and field (or question kind), worst severity first. P0 = silent wrong data, P1 = blocks a valid file, P2 = needless friction, P3 = edge case.

| Worst severity | Category | Field / kind | Documents | Examples |
|---|---|---|---|---|
| P0 | FALSE_ZERO_QUESTION | - | 3 | `L07_reparto_slash_mansione_ore_prog`, `L25_near_duplicate_hours_headers`, `B43_office_repeated_header_every_page` |
| P0 | PII_LEAK | - | 3 | `L56_office_front_desk_roster_csv`, `L62_neg_swapped_header_labels`, `C49_neg_payroll_with_names` |
| P0 | TABLE_BOUNDARY_WRONG | - | 3 | `B43_office_repeated_header_every_page`, `B57_isolation_last_minute_booking_com`, `B58_isolation_last_minute_walk_in` |
| P0 | FIELD_WRONG | net_amount | 2 | `C42_near_identical_net_headers`, `CO04_vat_register_two_rates_two_dates` |
| P0 | UNSAFE_IMPORT | - | 2 | `C42_near_identical_net_headers`, `CO04_vat_register_two_rates_two_dates` |
| P0 | FIELD_WRONG | planned_hours | 1 | `L25_near_duplicate_hours_headers` |
| P1 | DOMAIN_WRONG | - | 6 | `L32_grid_generic_day_columns`, `LO15_abbreviated_department_header_and_codes`, `B44_office_airbnb_style_export_no_channel_column` |
| P1 | FIELD_MISSED | room_revenue | 5 | `B08_abbreviated_headers`, `B40_office_pms_export_colored_header`, `B41_office_channel_manager_extract` |
| P1 | FIELD_MISSED | check_out | 4 | `B34_dates_day_month_name_text`, `B44_office_airbnb_style_export_no_channel_column`, `BO03_channel_manager_abbreviations` |
| P1 | FIELD_MISSED | invoice_number | 4 | `C07_imponibile_only`, `C40_two_level_header_importi`, `C47_office_supplier_invoices_with_notes` |
| P1 | FIELD_MISSED | planned_hours | 3 | `L07_reparto_slash_mansione_ore_prog`, `L57_office_kitchen_and_restaurant_two_sheets`, `LO13_hours_written_with_a_unit` |
| P1 | FIELD_MISSED | actual_hours | 3 | `L23_two_level_header_hours_over_planned_actual`, `L57_office_kitchen_and_restaurant_two_sheets`, `LO13_hours_written_with_a_unit` |
| P1 | FIELD_MISSED | source_record_id | 3 | `B06_ref_portale_totale_soggiorno`, `BO01_channel_written_as_codes`, `BO03_channel_manager_abbreviations` |
| P1 | FIELD_MISSED | check_in | 3 | `B34_dates_day_month_name_text`, `B44_office_airbnb_style_export_no_channel_column`, `BO07_weekday_prefixed_dates` |
| P1 | HEADER_WRONG | - | 2 | `L23_two_level_header_hours_over_planned_actual`, `C40_two_level_header_importi` |
| P1 | FIELD_MISSED | booked_at | 2 | `B34_dates_day_month_name_text`, `BO03_channel_manager_abbreviations` |
| P1 | FIELD_WRONG | check_in | 2 | `B50_neg_arrival_and_departure_swapped`, `B64_adv_near_identical_date_headers` |
| P1 | FIELD_MISSED | channel | 2 | `BO01_channel_written_as_codes`, `BO03_channel_manager_abbreviations` |
| P1 | FIELD_MISSED | net_amount | 2 | `C02_english_amount_excl_vat`, `CO09_amounts_with_eur_suffix_text` |
| P1 | FIELD_MISSED | line_description | 2 | `C05_net_vat_gross_amount_english`, `C46_office_manual_expense_sheet` |
| P1 | FIELD_WRONG | cost_category | 2 | `C43_reordered_with_junk_columns`, `CO03_cost_centre_and_department_columns` |
| P1 | FIELD_MISSED | supplier_name | 2 | `C45_office_cost_ledger_csv_semicolon`, `C46_office_manual_expense_sheet` |
| P1 | FIELD_MISSED | work_date | 1 | `L45_dates_weekday_prefix_text` |
| P1 | FIELD_WRONG | room_revenue | 1 | `B07_room_revenue_and_total_stay_both` |
| P1 | FIELD_WRONG | check_out | 1 | `B50_neg_arrival_and_departure_swapped` |
| P2 | QUESTION_UNNECESSARY | COLUMN_MEANING | 62 | `L04_alias_dept_hprev_consuntivo`, `L23_two_level_header_hours_over_planned_actual`, `L42_pii_name_and_company_email` |
| P2 | QUESTION_UNNECESSARY | VALUE_LABELS | 20 | `L18_sheet_per_department`, `L36_abbreviations_known`, `L39_known_italian_department_words` |
| P2 | QUESTION_UNNECESSARY | DOMAIN | 12 | `L32_grid_generic_day_columns`, `L65_neg_restaurant_menu_other_domain`, `LO15_abbreviated_department_header_and_codes` |
| P2 | QUESTION_UNNECESSARY | AMOUNT_BASIS | 6 | `C02_english_amount_excl_vat`, `C11_only_gross_stated_vat_included`, `C41_duplicate_importo_columns` |
| P2 | QUESTION_UNNECESSARY | DEPARTMENT_ROWS | 4 | `L09_centro_operativo`, `L66_neg_bookings_file_on_staff_card`, `LO07_department_in_a_label_value_block` |

Headers the truth says are a business field and NINFA did not recognise:

| Card | Field | Header not recognised | Documents |
|---|---|---|---|
| bookings | booked_at | 'Bkd' | `BO03_channel_manager_abbreviations` |
| bookings | booked_at | 'Data prenotazione' | `B34_dates_day_month_name_text` |
| bookings | channel | 'Can.' | `BO01_channel_written_as_codes` |
| bookings | channel | 'Src' | `BO03_channel_manager_abbreviations` |
| bookings | check_in | 'Arrivo' | `B34_dates_day_month_name_text`, `BO07_weekday_prefixed_dates` |
| bookings | check_in | 'Start date' | `B44_office_airbnb_style_export_no_channel_column` |
| bookings | check_out | 'Dep' | `BO03_channel_manager_abbreviations` |
| bookings | check_out | 'End date' | `B44_office_airbnb_style_export_no_channel_column` |
| bookings | check_out | 'Partenza' | `B34_dates_day_month_name_text`, `BO07_weekday_prefixed_dates` |
| bookings | commission_rate | 'Commissione %' | `B25_ota_channels_with_commission_columns` |
| bookings | room_revenue | 'Earnings' | `B44_office_airbnb_style_export_no_channel_column` |
| bookings | room_revenue | 'Imp. cam.' | `B08_abbreviated_headers` |
| bookings | room_revenue | 'Imp. camere' | `B40_office_pms_export_colored_header` |
| bookings | room_revenue | 'Imp.' | `BO01_channel_written_as_codes` |
| bookings | room_revenue | 'Total' | `B41_office_channel_manager_extract` |
| bookings | source_record_id | 'Cod.' | `BO01_channel_written_as_codes` |
| bookings | source_record_id | 'Ref.' | `B06_ref_portale_totale_soggiorno` |
| bookings | source_record_id | 'Res #' | `BO03_channel_manager_abbreviations` |
| bookings | total_revenue | 'Importi / Totale' | `B36_two_level_header` |
| bookings | total_revenue | 'Totale soggiorno' | `B07_room_revenue_and_total_stay_both` |
| costs | cost_category | 'Voce' | `C17_everyday_category_words_luce_acqua_gas` |
| costs | document_type | 'Tipo' | `C33_credit_notes_negative_amounts` |
| costs | invoice_number | 'Doc.' | `CO03_cost_centre_and_department_columns` |
| costs | invoice_number | 'Num.' | `C47_office_supplier_invoices_with_notes` |
| costs | invoice_number | 'Numero' | `C07_imponibile_only`, `C40_two_level_header_importi` |
| costs | line_description | 'Cosa' | `C46_office_manual_expense_sheet` |
| costs | line_description | 'Item' | `C05_net_vat_gross_amount_english` |
| costs | net_amount | 'Amount excl. VAT' | `C02_english_amount_excl_vat` |
| costs | net_amount | 'Imponibile' | `CO09_amounts_with_eur_suffix_text` |
| costs | supplier_name | 'Da chi' | `C46_office_manual_expense_sheet` |
| costs | supplier_name | 'Intestatario' | `C45_office_cost_ledger_csv_semicolon` |
| labor | actual_hours | 'Eff.' | `L57_office_kitchen_and_restaurant_two_sheets` |
| labor | actual_hours | 'Ore / Svolte' | `L23_two_level_header_hours_over_planned_actual` |
| labor | actual_hours | 'Ore effettive' | `LO13_hours_written_with_a_unit` |
| labor | department | 'Centro operativo' | `L09_centro_operativo` |
| labor | department | 'Rep.' | `LO15_abbreviated_department_header_and_codes` |
| labor | planned_hours | 'Ore previste' | `LO13_hours_written_with_a_unit` |
| labor | planned_hours | 'Ore prog.' | `L07_reparto_slash_mansione_ore_prog` |
| labor | planned_hours | 'Prev.' | `L57_office_kitchen_and_restaurant_two_sheets` |
| labor | work_date | 'Giorno' | `L45_dates_weekday_prefix_text` |

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

**`L04_alias_dept_hprev_consuntivo`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Dept'; planned_hours <- column 'H previste'; actual_hours <- column 'Consuntivo ore'
- mapping observed: actual_hours <- column 'Consuntivo ore' [HIGH]; department <- column 'Dept' [HIGH]; planned_hours <- column 'H previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 3 HIGH, 1 LOW
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Dept[HIGH], planned_hours<-H previste[LOW], actual_hours<-Consuntivo ore[HIGH]; asked: COLUMN_MEANING(H previste)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'H previste' could have been avoided

**`L07_reparto_slash_mansione_ore_prog`** - FALSE_ZERO_QUESTION, FIELD_MISSED (P0)
- card: labor - truth says: READY - NINFA: READY (automatic)
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto / Mansione'; planned_hours <- column 'Ore prog.'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto / Mansione' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 3 HIGH
- why: level READY; kind LABOR/HIGH (LABOR=0.94, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto / Mansione[HIGH], actual_hours<-Ore effettive[HIGH]
  - FIELD_MISSED [P2]: planned_hours not recognised
  - FALSE_ZERO_QUESTION [P0]: offered as automatic with: planned_hours missed

**`L09_centro_operativo`** - FIELD_MISSED, QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Centro operativo'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: DEPARTMENT_ROWS
- confidence: kind HIGH; fields 3 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.747, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: DEPARTMENT_ROWS
  - FIELD_MISSED [P2]: department not recognised
  - QUESTION_UNNECESSARY [P2]: DEPARTMENT_ROWS could have been avoided

**`L18_sheet_per_department`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- sheet; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- sheet [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 4 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.82, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH], role<-sheet[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Ristorante could have been avoided

**`L23_two_level_header_hours_over_planned_actual`** - FIELD_MISSED, HEADER_WRONG, QUESTION_UNNECESSARY (P1)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Giorno'; department <- column 'Reparto'; planned_hours <- column 'Ore / Programmate'; actual_hours <- column 'Ore / Svolte'
- mapping observed: department <- column 'Reparto' [HIGH]; planned_hours <- column 'Programmate' [HIGH]; work_date <- column 'Giorno' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 2 HIGH, 1 LOW
- why: level ASK; kind LABOR/HIGH (LABOR=0.747, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Giorno[HIGH], role<-Reparto[HIGH], planned_hours<-Programmate[LOW]; asked: COLUMN_MEANING(Programmate)
  - HEADER_WRONG [P1]: header found on another row
  - FIELD_MISSED [P2]: actual_hours not recognised
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Programmate' could have been avoided

**`L25_near_duplicate_hours_headers`** - FALSE_ZERO_QUESTION, FIELD_WRONG, QUESTION_MISSING (P0)
- card: labor - truth says: ASK - NINFA: READY (automatic)
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: COLUMN_MEANING - asked: none
- confidence: kind HIGH; fields 4 HIGH
- why: level READY; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]
  - FIELD_WRONG [P0]: planned_hours decided without asking (column 'Ore previste' [HIGH]); the document does not say
  - FALSE_ZERO_QUESTION [P0]: offered as automatic, but the document needs COLUMN_MEANING
  - QUESTION_MISSING [P3]: COLUMN_MEANING was not asked (READY)

**`L32_grid_generic_day_columns`** - DOMAIN_WRONG, QUESTION_UNNECESSARY (P2)
- card: labor - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected labor, detected other (LOW)
- mapping expected: -
- mapping observed: department <- column 'Reparto' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind LOW; fields 1 HIGH
- why: level MANUAL; read: role<-Reparto[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as other (None/LOW)
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`L36_abbreviations_known`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 3 HIGH, 1 MEDIUM
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[MEDIUM], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about F&B, FO, HK, HSKP, REC could have been avoided

**`L39_known_italian_department_words`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 4 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Ricevimento could have been avoided

**`L40_vocabulary_restaurant_bar_governante`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 3 HIGH, 1 MEDIUM
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[MEDIUM], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Ristorante, Governante, Portineria could have been avoided

**`L42_pii_name_and_company_email`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; planned_hours <- column 'Ore prev.'; actual_hours <- column 'Ore eff.'
- mapping observed: actual_hours <- column 'Ore eff.' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore prev.' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 2 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.687, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[HIGH]; asked: COLUMN_MEANING(Ore prev.), COLUMN_MEANING(Ore eff.)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore prev.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore eff.' could have been avoided

**`L45_dates_weekday_prefix_text`** - FIELD_MISSED (P1)
- card: labor - truth says: READY - NINFA: BLOCKED
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Giorno'; department <- column 'Reparto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 3 HIGH
- why: level BLOCKED; kind LABOR/HIGH (LABOR=0.747, BOOKINGS=0.0, COSTS=0.0); read: role<-Reparto[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; blocked: PERIOD_SUMMARY_ONLY
  - FIELD_MISSED [P1]: work_date not recognised

**`L54_office_weekly_roster_final`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Giorno'; department <- column 'Reparto'; planned_hours <- column 'Ore pian.'; actual_hours <- column 'Ore eff.'
- mapping observed: actual_hours <- column 'Ore eff.' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore pian.' [HIGH]; work_date <- column 'Giorno' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 2 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.687, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Giorno[HIGH], role<-Reparto[HIGH]; asked: COLUMN_MEANING(Ore pian.), COLUMN_MEANING(Ore eff.)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore pian.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore eff.' could have been avoided

**`L56_office_front_desk_roster_csv`** - PII_LEAK (P0)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- title; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- title [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: DEPARTMENT_CONFIRM
- confidence: kind HIGH; fields 3 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.747, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: DEPARTMENT_CONFIRM
  - PII_LEAK [P0]: 3 personal values are in the answer sent to the browser

**`L57_office_kitchen_and_restaurant_two_sheets`** - FIELD_MISSED (P1)
- card: labor - truth says: READY - NINFA: MANUAL
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Giorno'; department <- sheet; planned_hours <- column 'Prev.'; actual_hours <- column 'Eff.'
- mapping observed: department <- sheet [HIGH]; work_date <- column 'Giorno' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 2 HIGH
- why: level MANUAL; kind LABOR/HIGH (LABOR=0.687, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Giorno[HIGH], role<-sheet[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: planned_hours not recognised
  - FIELD_MISSED [P1]: actual_hours not recognised

**`L58_office_names_in_two_columns_and_comments`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'gg'; department <- column 'Reparto'; planned_hours <- column 'Ore Prev.'; actual_hours <- column 'Ore Lav.'
- mapping observed: actual_hours <- column 'Ore Lav.' [HIGH]; department <- column 'Reparto' [HIGH]; planned_hours <- column 'Ore Prev.' [HIGH]; work_date <- column 'gg' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 1 HIGH, 1 MEDIUM
- why: level ASK; kind LABOR/HIGH (LABOR=0.687, BOOKINGS=0.205, COSTS=0.164); read: work_date<-gg[MEDIUM], role<-Reparto[HIGH]; asked: COLUMN_MEANING(Ore Prev.), COLUMN_MEANING(Ore Lav.), COLUMN_MEANING(gg)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore Prev.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore Lav.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'gg' could have been avoided

**`L60_neg_totals_by_person_only`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: REJECT - NINFA: BLOCKED
- kind of data: expected labor, detected labor (MEDIUM)
- mapping expected: -
- mapping observed: department <- column 'Reparto' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind MEDIUM; fields 1 HIGH
- why: level BLOCKED; kind LABOR/MEDIUM (LABOR=0.433, COSTS=0.048, BOOKINGS=0.0); read: role<-Reparto[HIGH]; asked: COLUMN_MEANING(Totale ore); blocked: PERIOD_SUMMARY_ONLY
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Totale ore' could have been avoided

**`L62_neg_swapped_header_labels`** - PII_LEAK, QUESTION_UNNECESSARY (P0)
- card: labor - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: -
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Reparto' [MEDIUM]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 3 HIGH, 1 MEDIUM
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[MEDIUM], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: VALUE_LABELS
  - PII_LEAK [P0]: personal column 'Reparto' became role
  - PII_LEAK [P0]: 6 personal values are in the answer sent to the browser
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Chiara Carrara, Davide Dallari, Elena Orlandi, Giulia Ferretti, Marco Rinaldi, Matteo Olivieri could have been avoided

**`L65_neg_restaurant_menu_other_domain`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: department <- column 'Categoria' [MEDIUM]
- questions expected: none - asked: DOMAIN, VALUE_LABELS
- confidence: kind LOW; fields 1 MEDIUM
- why: level MANUAL; read: role<-Categoria[MEDIUM]; asked: DOMAIN, VALUE_LABELS; blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Contorni, Dessert, Primi, Secondi could have been avoided

**`L66_neg_bookings_file_on_staff_card`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: -
- mapping observed: -
- questions expected: DOMAIN - asked: DOMAIN, DEPARTMENT_ROWS
- confidence: kind HIGH; fields none
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.897, COSTS=0.328, LABOR=0.0); asked: DOMAIN, DEPARTMENT_ROWS; blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DEPARTMENT_ROWS could have been avoided

**`L69_adv_very_long_cell_and_odd_headers`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Re​parto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Re​parto' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 3 HIGH, 1 MEDIUM
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.328, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Re​parto[MEDIUM], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: COLUMN_MEANING(Re​parto)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Re\u200bparto' could have been avoided

**`LO02_payroll_monthly_summary_by_qualifica`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: REJECT - NINFA: BLOCKED
- kind of data: expected labor, detected labor (MEDIUM)
- mapping expected: -
- mapping observed: department <- column 'Qualifica' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING, VALUE_LABELS
- confidence: kind MEDIUM; fields 1 HIGH
- why: level BLOCKED; kind LABOR/MEDIUM (LABOR=0.433, COSTS=0.048, BOOKINGS=0.03); read: role<-Qualifica[HIGH]; asked: COLUMN_MEANING(Ore ord.), COLUMN_MEANING(Ore straord.), VALUE_LABELS; blocked: PERIOD_SUMMARY_ONLY
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore ord.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore straord.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Barista could have been avoided

**`LO06_job_titles_in_qualifica_column`** - QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Qualifica'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; department <- column 'Qualifica' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 4 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=1.0, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Qualifica[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Barista, Manutentore could have been avoided

**`LO07_department_in_a_label_value_block`** - FIELD_MISSED, QUESTION_UNNECESSARY (P2)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- title; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: actual_hours <- column 'Ore effettive' [HIGH]; planned_hours <- column 'Ore previste' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: DEPARTMENT_ROWS
- confidence: kind HIGH; fields 3 HIGH
- why: level ASK; kind LABOR/HIGH (LABOR=0.747, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], planned_hours<-Ore previste[HIGH], actual_hours<-Ore effettive[HIGH]; asked: DEPARTMENT_ROWS
  - FIELD_MISSED [P2]: department not recognised
  - QUESTION_UNNECESSARY [P2]: DEPARTMENT_ROWS could have been avoided

**`LO13_hours_written_with_a_unit`** - FIELD_MISSED (P1)
- card: labor - truth says: READY - NINFA: MANUAL
- kind of data: expected labor, detected labor (HIGH)
- mapping expected: work_date <- column 'Data'; department <- column 'Reparto'; planned_hours <- column 'Ore previste'; actual_hours <- column 'Ore effettive'
- mapping observed: department <- column 'Reparto' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 2 HIGH
- why: level MANUAL; kind LABOR/HIGH (LABOR=0.687, COSTS=0.164, BOOKINGS=0.102); read: work_date<-Data[HIGH], role<-Reparto[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: planned_hours not recognised
  - FIELD_MISSED [P1]: actual_hours not recognised

**`LO15_abbreviated_department_header_and_codes`** - DOMAIN_WRONG, FIELD_MISSED, QUESTION_UNNECESSARY (P1)
- card: labor - truth says: READY - NINFA: ASK
- kind of data: expected labor, detected other (LOW)
- mapping expected: work_date <- column 'Data'; department <- column 'Rep.'; planned_hours <- column 'Ore pian.'; actual_hours <- column 'Ore eff.'
- mapping observed: actual_hours <- column 'Ore eff.' [HIGH]; planned_hours <- column 'Ore pian.' [HIGH]; work_date <- column 'Data' [HIGH]
- questions expected: none - asked: DOMAIN, DEPARTMENT_ROWS, COLUMN_MEANING, COLUMN_MEANING
- confidence: kind LOW; fields 1 HIGH
- why: level ASK; read: work_date<-Data[HIGH]; asked: DOMAIN, DEPARTMENT_ROWS, COLUMN_MEANING(Ore pian.), COLUMN_MEANING(Ore eff.)
  - DOMAIN_WRONG [P1]: read as other (None/LOW)
  - FIELD_MISSED [P2]: department not recognised
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: DEPARTMENT_ROWS could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore pian.' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ore eff.' could have been avoided

**`B01_csv_italian_canonical`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B02_npren_prenotato_il_dal_al`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'N. pren.'; booked_at <- column 'Prenotato il'; check_in <- column 'Dal'; check_out <- column 'Al'; channel <- column 'Provenienza'; room_revenue <- column 'Ricavo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Prenotato il' [HIGH]; channel <- column 'Provenienza' [HIGH]; check_in <- column 'Dal' [HIGH]; check_out <- column 'Al' [HIGH]; room_revenue <- column 'Ricavo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'N. pren.' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, LABOR=0.0, COSTS=0.0); read: source_record_id<-N. pren.[HIGH], booked_at<-Prenotato il[HIGH], check_in<-Dal[HIGH], check_out<-Al[HIGH], channel<-Provenienza[MEDIUM], room_revenue<-Ricavo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Provenienza)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Provenienza' could have been avoided

**`B04_english_reservation_id_creation_date`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Reservation ID'; booked_at <- column 'Creation date'; check_in <- column 'Arrival date'; check_out <- column 'Departure'; channel <- column 'Channel'; room_revenue <- column 'Revenue'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Creation date' [HIGH]; channel <- column 'Channel' [HIGH]; check_in <- column 'Arrival date' [HIGH]; check_out <- column 'Departure' [HIGH]; room_revenue <- column 'Revenue' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Reservation ID' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, LABOR=0.253, COSTS=0.164); read: source_record_id<-Reservation ID[HIGH], booked_at<-Creation date[HIGH], check_in<-Arrival date[HIGH], check_out<-Departure[HIGH], channel<-Channel[MEDIUM], room_revenue<-Revenue[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Channel)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Channel' could have been avoided

**`B06_ref_portale_totale_soggiorno`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Ref.'; booked_at <- column 'Data prenotazione'; check_in <- column 'Check in'; check_out <- column 'Check-out'; channel <- column 'Portale'; room_revenue <- column 'Totale soggiorno'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Portale' [HIGH]; check_in <- column 'Check in' [HIGH]; check_out <- column 'Check-out' [HIGH]; room_revenue <- column 'Totale soggiorno' [HIGH]; rooms <- column 'Camere' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 7 HIGH
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.897, COSTS=0.212, LABOR=0.0); read: booked_at<-Data prenotazione[HIGH], check_in<-Check in[HIGH], check_out<-Check-out[HIGH], channel<-Portale[HIGH], room_revenue<-Totale soggiorno[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: source_record_id not recognised

**`B07_room_revenue_and_total_stay_both`** - FIELD_MISSED, FIELD_WRONG, QUESTION_UNNECESSARY (P1)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; total_revenue <- column 'Totale soggiorno'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Totale soggiorno' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.376, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Totale soggiorno[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - FIELD_WRONG [P1]: room_revenue read from column 'Totale soggiorno' [HIGH]
  - FIELD_MISSED [P2]: total_revenue not recognised
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B08_abbreviated_headers`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'N.pren.'; booked_at <- column 'Data pren.'; check_in <- column 'Arr.'; check_out <- column 'Part.'; channel <- column 'Canale vend.'; room_revenue <- column 'Imp. cam.'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data pren.' [HIGH]; channel <- column 'Canale vend.' [MEDIUM]; check_in <- column 'Arr.' [HIGH]; check_out <- column 'Part.' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'N.pren.' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH, 1 MEDIUM
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.897, LABOR=0.253, COSTS=0.164); read: source_record_id<-N.pren.[HIGH], booked_at<-Data pren.[HIGH], check_in<-Arr.[HIGH], check_out<-Part.[HIGH], channel<-Canale vend.[MEDIUM], status<-Stato[HIGH], rooms<-Camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: room_revenue not recognised

**`B09_mixed_italian_english_headers`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Booked at'; check_in <- column 'Check-in'; check_out <- column 'Check-out'; channel <- column 'Channel'; room_revenue <- column 'Totale soggiorno'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Booked at' [HIGH]; channel <- column 'Channel' [HIGH]; check_in <- column 'Check-in' [HIGH]; check_out <- column 'Check-out' [HIGH]; room_revenue <- column 'Totale soggiorno' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.048, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Booked at[HIGH], check_in<-Check-in[HIGH], check_out<-Check-out[HIGH], channel<-Channel[MEDIUM], room_revenue<-Totale soggiorno[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Channel)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Channel' could have been avoided

**`B10_guest_name_email_phone_notes`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B11_guest_column_holds_names_not_a_count`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Booking ID'; booked_at <- column 'Created'; check_in <- column 'Arrival'; check_out <- column 'Departure'; channel <- column 'Source'; room_revenue <- column 'Room revenue'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Created' [HIGH]; channel <- column 'Source' [HIGH]; check_in <- column 'Arrival' [HIGH]; check_out <- column 'Departure' [HIGH]; room_revenue <- column 'Room revenue' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Booking ID' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 6 HIGH, 1 LOW, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.927, LABOR=0.0, COSTS=0.0); read: source_record_id<-Booking ID[HIGH], booked_at<-Created[LOW], check_in<-Arrival[HIGH], check_out<-Departure[HIGH], channel<-Source[MEDIUM], room_revenue<-Room revenue[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Created), COLUMN_MEANING(Source)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Created' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Source' could have been avoided

**`B12_guests_count_column_and_guest_name`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'; guests <- column 'Ospiti'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; guests <- column 'Ospiti' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 8 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH], guests<-Ospiti[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B13_pax_and_num_ospiti`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'; guests <- column 'Pax'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; guests <- column 'Pax' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 8 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH], guests<-Pax[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B14_booker_and_guest_names_two_columns`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Book Number'; check_in <- column 'Check-in'; check_out <- column 'Check-out'; booked_at <- column 'Booked on'; status <- column 'Status'; channel <- column 'Channel'; room_revenue <- column 'Price'; guests <- column 'Persons'; rooms <- column 'Rooms'
- mapping observed: booked_at <- column 'Booked on' [HIGH]; channel <- column 'Channel' [HIGH]; check_in <- column 'Check-in' [HIGH]; check_out <- column 'Check-out' [HIGH]; guests <- column 'Persons' [LOW]; room_revenue <- column 'Price' [HIGH]; rooms <- column 'Rooms' [HIGH]; source_record_id <- column 'Book Number' [HIGH]; status <- column 'Status' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 5 HIGH, 1 LOW, 2 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.748, COSTS=0.048, LABOR=0.0); read: source_record_id<-Book Number[MEDIUM], check_in<-Check-in[HIGH], check_out<-Check-out[HIGH], booked_at<-Booked on[HIGH], status<-Status[HIGH], channel<-Channel[MEDIUM], guests<-Persons[LOW], rooms<-Rooms[HIGH]; asked: COLUMN_MEANING(Price), COLUMN_MEANING(Book Number), COLUMN_MEANING(Channel)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Price' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Book Number' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Channel' could have been avoided

**`B15_title_before_table`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B16_notes_below_the_table`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B17_summary_block_before_table`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B19_dashboard_bookings_and_legend_sheets`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B20_sheet_per_month_same_columns`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.253); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B21_two_tables_confirmed_and_cancelled`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: ASK - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: TABLE - asked: TABLE, COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: TABLE, COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B22_status_and_cancellation_date`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'; cancelled_at <- column 'Data cancellazione'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; cancelled_at <- column 'Data cancellazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 8 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.253); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH], cancelled_at<-Data cancellazione[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B23_status_modificata_is_ambiguous`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: ASK - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; rooms <- column 'Camere'; status <- column 'Stato'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: VALUE_LABELS - asked: VALUE_LABELS, COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], rooms<-Camere[HIGH], status<-Stato[HIGH]; asked: VALUE_LABELS, COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B24_channels_direct_phone_email_walkin`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B25_ota_channels_with_commission_columns`** - FIELD_MISSED (P2)
- card: bookings - truth says: READY - NINFA: READY (automatic)
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'; commission_rate <- column 'Commissione %'; commission_amount <- column 'Commissione'; room_type <- column 'Tipologia camera'; rate_plan <- column 'Tariffa'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; commission_amount <- column 'Commissione %' [HIGH]; rate_plan <- column 'Tariffa' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; room_type <- column 'Tipologia camera' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 11 HIGH
- why: level READY; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH], commission_amount<-Commissione %[HIGH], room_type<-Tipologia camera[HIGH], rate_plan<-Tariffa[HIGH]
  - FIELD_MISSED [P2]: commission_rate not recognised

**`B27_amounts_point_decimal_csv`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B28_amounts_with_euro_sign_text`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B29_amounts_excel_currency_format`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B30_dates_text_italian`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B31_dates_us_provable_csv`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Booking ID'; booked_at <- column 'Booked'; check_in <- column 'Arrival'; check_out <- column 'Departure'; channel <- column 'Channel'; room_revenue <- column 'Room revenue'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Booked' [HIGH]; channel <- column 'Channel' [HIGH]; check_in <- column 'Arrival' [HIGH]; check_out <- column 'Departure' [HIGH]; room_revenue <- column 'Room revenue' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Booking ID' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, LABOR=0.0, COSTS=0.0); read: source_record_id<-Booking ID[HIGH], booked_at<-Booked[HIGH], check_in<-Arrival[HIGH], check_out<-Departure[HIGH], channel<-Channel[MEDIUM], room_revenue<-Room revenue[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Channel)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Channel' could have been avoided

**`B32_dates_ambiguous_day_month`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: ASK - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: DATE_ORDER - asked: DATE_ORDER, COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: DATE_ORDER(Data prenotazione), COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B33_dates_dotted_and_day_month_name`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B34_dates_day_month_name_text`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: channel <- column 'Canale' [MEDIUM]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 4 HIGH, 1 MEDIUM
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.693, COSTS=0.164, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: booked_at not recognised
  - FIELD_MISSED [P1]: check_in not recognised
  - FIELD_MISSED [P1]: check_out not recognised

**`B35_booking_timestamp_with_time`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data e ora prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data e ora prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data e ora prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B36_two_level_header`** - FIELD_MISSED, QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice'; booked_at <- column 'Data prenotazione'; check_in <- column 'Soggiorno / Arrivo'; check_out <- column 'Soggiorno / Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importi / Camere'; total_revenue <- column 'Importi / Totale'; status <- column 'Stato'; rooms <- column 'N. camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Soggiorno - Arrivo' [HIGH]; check_out <- column 'Soggiorno - Partenza' [HIGH]; room_revenue <- column 'Importi - Camere' [HIGH]; rooms <- column 'N. camere' [HIGH]; source_record_id <- column 'Codice' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 6 HIGH, 2 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.376, LABOR=0.0); read: source_record_id<-Codice[MEDIUM], booked_at<-Data prenotazione[HIGH], check_in<-Soggiorno - Arrivo[HIGH], check_out<-Soggiorno - Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importi - Camere[HIGH], status<-Stato[HIGH], rooms<-N. camere[HIGH]; asked: COLUMN_MEANING(Codice), COLUMN_MEANING(Canale)
  - FIELD_MISSED [P2]: total_revenue not recognised
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Codice' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B38_reordered_columns_with_junk`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: room_revenue <- column 'Importo camere'; check_in <- column 'Arrivo'; channel <- column 'Canale'; check_out <- column 'Partenza'; source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; rooms <- column 'N. camere'; status <- column 'Stato'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'N. camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: room_revenue<-Importo camere[HIGH], check_in<-Arrivo[HIGH], channel<-Canale[MEDIUM], check_out<-Partenza[HIGH], source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], rooms<-N. camere[HIGH], status<-Stato[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B39_ids_with_leading_zeros_and_numeric`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'N. prenotazione'; booked_at <- column 'Prenotato il'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Prenotato il' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'N. prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.164, LABOR=0.0); read: source_record_id<-N. prenotazione[HIGH], booked_at<-Prenotato il[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B40_office_pms_export_colored_header`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'N. Pren.'; booked_at <- column 'Data Pren.'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; status <- column 'Stato'; room_revenue <- column 'Imp. camere'; rooms <- column 'N. camere'
- mapping observed: booked_at <- column 'Data Pren.' [HIGH]; channel <- column 'Canale' [MEDIUM]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; rooms <- column 'N. camere' [HIGH]; source_record_id <- column 'N. Pren.' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH, 1 MEDIUM
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.897, LABOR=0.253, COSTS=0.164); read: source_record_id<-N. Pren.[HIGH], booked_at<-Data Pren.[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], status<-Stato[HIGH], rooms<-N. camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: room_revenue not recognised

**`B41_office_channel_manager_extract`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Res.ID'; booked_at <- column 'Booking date'; check_in <- column 'Check-in'; check_out <- column 'Check-out'; channel <- column 'Channel'; status <- column 'Status'; rooms <- column 'Rooms'; room_revenue <- column 'Total'
- mapping observed: booked_at <- column 'Booking date' [HIGH]; channel <- column 'Channel' [HIGH]; check_in <- column 'Check-in' [HIGH]; check_out <- column 'Check-out' [HIGH]; rooms <- column 'Rooms' [HIGH]; source_record_id <- column 'Res.ID' [HIGH]; status <- column 'Status' [HIGH]; total_revenue <- column 'Total' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 8 HIGH
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.748, LABOR=0.253, COSTS=0.212); read: source_record_id<-Res.ID[HIGH], booked_at<-Booking date[HIGH], check_in<-Check-in[HIGH], check_out<-Check-out[HIGH], channel<-Channel[HIGH], status<-Status[HIGH], rooms<-Rooms[HIGH], total_revenue<-Total[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: room_revenue not recognised

**`B42_office_front_desk_monthly_report`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice'; booked_at <- column 'Prenotata il'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Provenienza'; room_revenue <- column 'Ricavo'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Prenotata il' [HIGH]; channel <- column 'Provenienza' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Ricavo' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING, COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 5 HIGH, 2 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.897, LABOR=0.0, COSTS=0.0); read: source_record_id<-Codice[MEDIUM], booked_at<-Prenotata il[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Provenienza[MEDIUM], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Ricavo), COLUMN_MEANING(Codice), COLUMN_MEANING(Provenienza)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Ricavo' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Codice' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Provenienza' could have been avoided

**`B43_office_repeated_header_every_page`** - FALSE_ZERO_QUESTION, TABLE_BOUNDARY_WRONG (P0)
- card: bookings - truth says: READY - NINFA: READY (automatic)
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 8 HIGH
- why: level READY; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]
  - TABLE_BOUNDARY_WRONG [P0]: 8 records read, 24 in the document
  - FALSE_ZERO_QUESTION [P0]: offered as automatic with: table boundary wrong

**`B44_office_airbnb_style_export_no_channel_column`** - DOMAIN_WRONG, FIELD_MISSED, QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected other (LOW)
- mapping expected: source_record_id <- column 'Confirmation code'; status <- column 'Status'; check_in <- column 'Start date'; check_out <- column 'End date'; booked_at <- column 'Booked'; room_revenue <- column 'Earnings'
- mapping observed: booked_at <- column 'Booked' [HIGH]; source_record_id <- column 'Confirmation code' [HIGH]; status <- column 'Status' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind LOW; fields 3 HIGH
- why: level MANUAL; read: source_record_id<-Confirmation code[HIGH], status<-Status[HIGH], booked_at<-Booked[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as other (None/LOW)
  - FIELD_MISSED [P2]: check_in not recognised
  - FIELD_MISSED [P2]: check_out not recognised
  - FIELD_MISSED [P2]: room_revenue not recognised
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`B50_neg_arrival_and_departure_swapped`** - FIELD_WRONG, QUESTION_UNNECESSARY (P1)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - FIELD_WRONG [P1]: check_in decided without asking (column 'Arrivo' [HIGH]); the document does not say
  - FIELD_WRONG [P1]: check_out decided without asking (column 'Partenza' [HIGH]); the document does not say
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B51_neg_occupancy_calendar_not_bookings`** - DOMAIN_WRONG, QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected labor (MEDIUM)
- mapping expected: -
- mapping observed: room_type <- column 'Camera' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind MEDIUM; fields 1 HIGH
- why: level MANUAL; kind LABOR/MEDIUM (LABOR=0.507, BOOKINGS=0.21, COSTS=0.0); read: room_type<-Camera[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as labor (LABOR/MEDIUM)
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`B55_neg_checkout_before_arrival_rows`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B57_isolation_last_minute_booking_com`** - TABLE_BOUNDARY_WRONG (P0)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.795, LABOR=0.507, COSTS=0.328); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importo camere[HIGH]; blocked: MISSING_REQUIRED
  - TABLE_BOUNDARY_WRONG [P0]: 4 records read, 12 in the document

**`B58_isolation_last_minute_walk_in`** - TABLE_BOUNDARY_WRONG (P0)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.795, LABOR=0.507, COSTS=0.328); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[HIGH], room_revenue<-Importo camere[HIGH]; blocked: MISSING_REQUIRED
  - TABLE_BOUNDARY_WRONG [P0]: 4 records read, 12 in the document

**`B60_adv_hidden_sheet_with_older_bookings`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B61_adv_instructions_in_guest_notes`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B62_adv_formulas_and_html_in_cells`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B63_adv_total_word_in_a_notes_column`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B64_adv_near_identical_date_headers`** - FIELD_WRONG, QUESTION_UNNECESSARY (P1)
- card: bookings - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Check-in' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Check-in[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - FIELD_WRONG [P1]: check_in decided without asking (column 'Check-in' [HIGH]); the document does not say
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B65_adv_very_long_cells_and_unicode`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.492, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`B66_large_year_of_bookings`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`BO01_channel_written_as_codes`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Cod.'; booked_at <- column 'Data pren.'; check_in <- column 'Arr.'; check_out <- column 'Part.'; channel <- column 'Can.'; room_revenue <- column 'Imp.'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data pren.' [HIGH]; check_in <- column 'Arr.' [HIGH]; check_out <- column 'Part.' [HIGH]; rooms <- column 'Camere' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.693, LABOR=0.253, COSTS=0.164); read: booked_at<-Data pren.[HIGH], check_in<-Arr.[HIGH], check_out<-Part.[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: source_record_id not recognised
  - FIELD_MISSED [P1]: channel not recognised
  - FIELD_MISSED [P1]: room_revenue not recognised

**`BO02_arrivals_by_day_sections_no_ids`** - DOMAIN_WRONG, QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected bookings, detected other (LOW)
- mapping expected: -
- mapping observed: channel <- column 'Provenienza' [HIGH]
- questions expected: none - asked: DOMAIN, COLUMN_MEANING
- confidence: kind LOW; fields 1 HIGH
- why: level MANUAL; read: channel<-Provenienza[HIGH]; asked: DOMAIN, COLUMN_MEANING(Tot. €); blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P2]: read as other (None/LOW)
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Tot. €' could have been avoided

**`BO03_channel_manager_abbreviations`** - DOMAIN_WRONG, FIELD_MISSED, QUESTION_UNNECESSARY (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected other (LOW)
- mapping expected: source_record_id <- column 'Res #'; booked_at <- column 'Bkd'; check_in <- column 'Arr'; check_out <- column 'Dep'; channel <- column 'Src'; room_revenue <- column 'Tot'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: check_in <- column 'Arr' [HIGH]; room_revenue <- column 'Tot' [HIGH]; rooms <- column 'Camere' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: DOMAIN, COLUMN_MEANING
- confidence: kind LOW; fields 3 HIGH
- why: level MANUAL; read: check_in<-Arr[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: DOMAIN, COLUMN_MEANING(Tot); blocked: MISSING_REQUIRED
  - DOMAIN_WRONG [P1]: read as other (None/LOW)
  - FIELD_MISSED [P1]: source_record_id not recognised
  - FIELD_MISSED [P1]: booked_at not recognised
  - FIELD_MISSED [P1]: check_out not recognised
  - FIELD_MISSED [P1]: channel not recognised
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Tot' could have been avoided

**`BO04_front_desk_arrivals_list_no_booking_date`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: REJECT - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (MEDIUM)
- mapping expected: check_in <- column 'Dal'; check_out <- column 'Al'; channel <- column 'Provenienza'; room_revenue <- column 'Tot. €'
- mapping observed: channel <- column 'Provenienza' [MEDIUM]; check_in <- column 'Dal' [HIGH]; check_out <- column 'Al' [HIGH]; room_revenue <- column 'Tot. €' [HIGH]; rooms <- column 'Camere' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind MEDIUM; fields 3 HIGH, 1 MEDIUM
- why: level MANUAL; kind BOOKINGS/MEDIUM (BOOKINGS=0.59, COSTS=0.048, LABOR=0.0); read: rooms<-Camere[HIGH], check_in<-Dal[HIGH], check_out<-Al[HIGH], channel<-Provenienza[MEDIUM]; asked: COLUMN_MEANING(Tot. €); blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Tot. €' could have been avoided

**`BO05_kpi_block_beside_the_table`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`BO06_table_starts_in_column_c_frozen_panes`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`BO07_weekday_prefixed_dates`** - FIELD_MISSED (P1)
- card: bookings - truth says: READY - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [MEDIUM]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH, 1 MEDIUM
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.795, COSTS=0.328, LABOR=0.253); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: check_in not recognised
  - FIELD_MISSED [P1]: check_out not recognised

**`BO08_room_and_breakfast_revenue_columns`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camera'; total_revenue <- column 'Totale'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camera' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]; total_revenue <- column 'Totale' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 8 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.376, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camera[HIGH], total_revenue<-Totale[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`BO09_status_written_as_ok_canc_ns`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; rooms <- column 'Camere'; status <- column 'Stato'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: VALUE_LABELS, COLUMN_MEANING, COLUMN_MEANING
- confidence: kind HIGH; fields 6 HIGH, 2 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], rooms<-Camere[HIGH], status<-Stato[MEDIUM]; asked: VALUE_LABELS, COLUMN_MEANING(Canale), COLUMN_MEANING(Stato)
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about OK, CANC, NS could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Stato' could have been avoided

**`BO10_one_sheet_per_week`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.253); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`BO11_header_cells_with_line_breaks`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'N.
pren.'; booked_at <- column 'Data
prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale
di vendita'; room_revenue <- column 'Importo
camere (€)'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale di vendita' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere (€)' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'N. pren.' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=1.0, COSTS=0.328, LABOR=0.0); read: source_record_id<-N. pren.[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale di vendita[MEDIUM], room_revenue<-Importo camere (€)[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale di vendita)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale di vendita' could have been avoided

**`BO13_blank_row_between_every_record`** - QUESTION_UNNECESSARY (P2)
- card: bookings - truth says: READY - NINFA: ASK
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: source_record_id <- column 'Codice prenotazione'; booked_at <- column 'Data prenotazione'; check_in <- column 'Arrivo'; check_out <- column 'Partenza'; channel <- column 'Canale'; room_revenue <- column 'Importo camere'; status <- column 'Stato'; rooms <- column 'Camere'
- mapping observed: booked_at <- column 'Data prenotazione' [HIGH]; channel <- column 'Canale' [HIGH]; check_in <- column 'Arrivo' [HIGH]; check_out <- column 'Partenza' [HIGH]; room_revenue <- column 'Importo camere' [HIGH]; rooms <- column 'Camere' [HIGH]; source_record_id <- column 'Codice prenotazione' [HIGH]; status <- column 'Stato' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind BOOKINGS/HIGH (BOOKINGS=0.82, COSTS=0.328, LABOR=0.0); read: source_record_id<-Codice prenotazione[HIGH], booked_at<-Data prenotazione[HIGH], check_in<-Arrivo[HIGH], check_out<-Partenza[HIGH], channel<-Canale[MEDIUM], room_revenue<-Importo camere[HIGH], status<-Stato[HIGH], rooms<-Camere[HIGH]; asked: COLUMN_MEANING(Canale)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Canale' could have been avoided

**`C01_complete_register_consistent`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Totale'; currency <- column 'Valuta'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; currency <- column 'Valuta' [HIGH]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 8 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=1.0, LABOR=0.567, BOOKINGS=0.312); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH], currency<-Valuta[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C02_english_amount_excl_vat`** - FIELD_MISSED, QUESTION_UNNECESSARY (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Date'; invoice_number <- column 'Invoice no.'; supplier_name <- column 'Supplier'; line_description <- column 'Description'; cost_category <- column 'Category'; net_amount <- column 'Amount excl. VAT'; invoice_tax_amount <- column 'VAT'; invoice_gross_amount <- column 'Total'; currency <- column 'Currency'
- mapping observed: cost_category <- column 'Category' [MEDIUM]; currency <- column 'Currency' [HIGH]; invoice_date <- column 'Date' [HIGH]; invoice_gross_amount <- column 'Total' [MEDIUM]; invoice_number <- column 'Invoice no.' [HIGH]; invoice_tax_amount <- column 'VAT' [HIGH]; line_description <- column 'Description' [HIGH]; supplier_name <- column 'Supplier' [HIGH]
- questions expected: none - asked: AMOUNT_BASIS, VALUE_LABELS
- confidence: kind HIGH; fields 6 HIGH, 2 MEDIUM
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.704, LABOR=0.373, BOOKINGS=0.312); read: invoice_date<-Date[HIGH], invoice_number<-Invoice no.[HIGH], supplier_name<-Supplier[HIGH], line_description<-Description[HIGH], cost_category<-Category[MEDIUM], invoice_tax_amount<-VAT[HIGH], invoice_gross_amount<-Total[MEDIUM], currency<-Currency[HIGH]; asked: AMOUNT_BASIS(Total), VALUE_LABELS; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: net_amount not recognised
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Total' could have been avoided
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C05_net_vat_gross_amount_english`** - FIELD_MISSED (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Invoice date'; invoice_number <- column 'Invoice number'; supplier_name <- column 'Vendor'; line_description <- column 'Item'; net_amount <- column 'Net amount'; invoice_tax_amount <- column 'VAT'; invoice_gross_amount <- column 'Gross amount'
- mapping observed: invoice_date <- column 'Invoice date' [HIGH]; invoice_gross_amount <- column 'Gross amount' [HIGH]; invoice_number <- column 'Invoice number' [HIGH]; invoice_tax_amount <- column 'VAT' [HIGH]; net_amount <- column 'Net amount' [HIGH]; supplier_name <- column 'Vendor' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.704, LABOR=0.253, BOOKINGS=0.102); read: invoice_date<-Invoice date[HIGH], invoice_number<-Invoice number[HIGH], supplier_name<-Vendor[HIGH], line_total<-Net amount[HIGH], invoice_tax_amount<-VAT[HIGH], invoice_gross_amount<-Gross amount[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: line_description not recognised

**`C07_imponibile_only`** - FIELD_MISSED (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Numero'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; net_amount <- column 'Imponibile'
- mapping observed: invoice_date <- column 'Data' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 4 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.656, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: invoice_number not recognised

**`C11_only_gross_stated_vat_included`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; invoice_gross_amount <- column 'Totale IVA inclusa'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale IVA inclusa' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: AMOUNT_BASIS
- confidence: kind HIGH; fields 5 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.704, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], invoice_gross_amount<-Totale IVA inclusa[HIGH]; asked: AMOUNT_BASIS(Totale IVA inclusa); blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Totale IVA inclusa' could have been avoided

**`C16_eight_known_categories`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Totale'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, LABOR=0.507, BOOKINGS=0.312); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C17_everyday_category_words_luce_acqua_gas`** - FIELD_MISSED (P2)
- card: costs - truth says: READY - NINFA: READY (automatic)
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Voce'; net_amount <- column 'Netto'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Netto' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH
- why: level READY; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Netto[HIGH]
  - FIELD_MISSED [P2]: cost_category not recognised

**`C20_title_before_table`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Totale'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=1.0, LABOR=0.507, BOOKINGS=0.312); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C24_summary_sheet_and_register_sheet`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Totale'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=1.0, LABOR=0.507, BOOKINGS=0.312); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C33_credit_notes_negative_amounts`** - FIELD_MISSED, QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; document_type <- column 'Tipo'; net_amount <- column 'Imponibile'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [LOW]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 4 HIGH, 1 LOW
- why: level ASK; kind COSTS/HIGH (COSTS=0.704, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[LOW]; asked: COLUMN_MEANING(Imponibile)
  - FIELD_MISSED [P2]: document_type not recognised
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Imponibile' could have been avoided

**`C38_several_lines_per_invoice`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; net_amount <- column 'Imponibile'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 4 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[MEDIUM], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH]; asked: COLUMN_MEANING(N. documento)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'N. documento' could have been avoided

**`C40_two_level_header_importi`** - FIELD_MISSED, HEADER_WRONG (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Numero'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; net_amount <- column 'Importi / Imponibile'; invoice_tax_amount <- column 'Importi / IVA'; invoice_gross_amount <- column 'Importi / Totale'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.704, BOOKINGS=0.312, LABOR=0.253); read: invoice_date<-Data[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH]; blocked: MISSING_REQUIRED
  - HEADER_WRONG [P1]: header found on another row
  - FIELD_MISSED [P1]: invoice_number not recognised

**`C41_duplicate_importo_columns`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: NOT_AUTOMATIC - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'Importo (2)' [LOW]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Importo' [MEDIUM]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: AMOUNT_BASIS
- confidence: kind HIGH; fields 4 HIGH, 1 LOW, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Importo[MEDIUM], invoice_tax_amount<-Importo (2)[LOW]; asked: AMOUNT_BASIS(Importo)
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Importo' could have been avoided

**`C42_near_identical_net_headers`** - FIELD_WRONG, UNSAFE_IMPORT (P0)
- card: costs - truth says: NOT_AUTOMATIC - NINFA: READY (automatic)
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; invoice_tax_amount <- column 'IVA'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH
- why: level READY; kind COSTS/HIGH (COSTS=0.82, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH]
  - FIELD_WRONG [P0]: net_amount decided without asking (column 'Imponibile' [HIGH]); the document does not say
  - UNSAFE_IMPORT [P0]: offered as automatic, but the document needs a person

**`C43_reordered_with_junk_columns`** - FIELD_WRONG, QUESTION_UNNECESSARY (P1)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: net_amount <- column 'Imponibile'; supplier_name <- column 'Fornitore'; invoice_date <- column 'Data registrazione'; line_description <- column 'Descrizione'; invoice_number <- column 'N. fattura'
- mapping observed: cost_category <- column 'Centro di costo' [MEDIUM]; invoice_date <- column 'Data registrazione' [HIGH]; invoice_number <- column 'N. fattura' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 5 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, LABOR=0.253, BOOKINGS=0.21); read: cost_category<-Centro di costo[MEDIUM], line_total<-Imponibile[HIGH], supplier_name<-Fornitore[HIGH], invoice_date<-Data registrazione[HIGH], line_description<-Descrizione[HIGH], invoice_number<-N. fattura[HIGH]; asked: VALUE_LABELS
  - FIELD_WRONG [P1]: cost_category claimed from column 'Centro di costo' [MEDIUM], a column that must stay out of the import
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about CC01 could have been avoided

**`C44_office_accounting_export_header_on_row_five`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data reg.'; invoice_number <- column 'Num. doc.'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione operazione'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Tot. doc.'
- mapping observed: invoice_date <- column 'Data reg.' [HIGH]; invoice_gross_amount <- column 'Tot. doc.' [HIGH]; invoice_number <- column 'Num. doc.' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione operazione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: COLUMN_MEANING
- confidence: kind HIGH; fields 6 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=1.0, LABOR=0.253, BOOKINGS=0.102); read: invoice_date<-Data reg.[MEDIUM], invoice_number<-Num. doc.[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione operazione[HIGH], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Tot. doc.[HIGH]; asked: COLUMN_MEANING(Data reg.)
  - QUESTION_UNNECESSARY [P2]: COLUMN_MEANING on 'Data reg.' could have been avoided

**`C45_office_cost_ledger_csv_semicolon`** - FIELD_MISSED, QUESTION_UNNECESSARY (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Documento'; supplier_name <- column 'Intestatario'; line_description <- column 'Causale'; cost_category <- column 'Conto'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'Iva'; invoice_gross_amount <- column 'Totale doc'
- mapping observed: cost_category <- column 'Conto' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale doc' [HIGH]; invoice_number <- column 'Documento' [HIGH]; invoice_tax_amount <- column 'Iva' [HIGH]; line_description <- column 'Causale' [HIGH]; net_amount <- column 'Imponibile' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 6 HIGH, 1 MEDIUM
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.704, LABOR=0.253, BOOKINGS=0.102); read: invoice_date<-Data[HIGH], invoice_number<-Documento[HIGH], line_description<-Causale[HIGH], cost_category<-Conto[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-Iva[HIGH], invoice_gross_amount<-Totale doc[HIGH]; asked: VALUE_LABELS; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: supplier_name not recognised
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`C46_office_manual_expense_sheet`** - FIELD_MISSED (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (MEDIUM)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Fatt. n.'; supplier_name <- column 'Da chi'; line_description <- column 'Cosa'; cost_category <- column 'Tipo spesa'; net_amount <- column 'Importo netto'
- mapping observed: cost_category <- column 'Tipo spesa' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'Fatt. n.' [LOW]; net_amount <- column 'Importo netto' [HIGH]
- questions expected: none - asked: none
- confidence: kind MEDIUM; fields 2 HIGH, 1 LOW, 1 MEDIUM
- why: level MANUAL; kind COSTS/MEDIUM (COSTS=0.604, LABOR=0.253, BOOKINGS=0.102); read: invoice_date<-Data[HIGH], invoice_number<-Fatt. n.[LOW], cost_category<-Tipo spesa[MEDIUM], line_total<-Importo netto[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: supplier_name not recognised
  - FIELD_MISSED [P1]: line_description not recognised

**`C47_office_supplier_invoices_with_notes`** - FIELD_MISSED (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Num.'; supplier_name <- column 'Fornitore'; line_description <- column 'Oggetto'; net_amount <- column 'Imponibile €'; invoice_tax_amount <- column 'IVA €'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_tax_amount <- column 'IVA €' [HIGH]; line_description <- column 'Oggetto' [HIGH]; net_amount <- column 'Imponibile €' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 5 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.884, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Oggetto[HIGH], line_total<-Imponibile €[HIGH], invoice_tax_amount<-IVA €[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: invoice_number not recognised

**`C48_neg_bank_statement`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: invoice_date <- column 'Data valuta' [MEDIUM]; line_description <- column 'Descrizione' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind LOW; fields 1 HIGH, 1 MEDIUM
- why: level MANUAL; read: invoice_date<-Data valuta[MEDIUM], line_description<-Descrizione[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`C49_neg_payroll_with_names`** - PII_LEAK, QUESTION_UNNECESSARY (P0)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: invoice_gross_amount <- column 'Lordo' [HIGH]; net_amount <- column 'Netto in busta' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind LOW; fields 2 HIGH
- why: level MANUAL; read: invoice_gross_amount<-Lordo[HIGH], line_total<-Netto in busta[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - PII_LEAK [P0]: 3 personal values are in the answer sent to the browser
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`C51_neg_bookings_on_costs_card`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: NOT_AUTOMATIC - NINFA: MANUAL
- kind of data: expected bookings, detected bookings (HIGH)
- mapping expected: -
- mapping observed: invoice_date <- column 'Data prenotazione' [MEDIUM]; net_amount <- column 'Importo camere' [MEDIUM]
- questions expected: DOMAIN - asked: DOMAIN, AMOUNT_BASIS
- confidence: kind HIGH; fields 2 MEDIUM
- why: level MANUAL; kind BOOKINGS/HIGH (BOOKINGS=0.795, COSTS=0.328, LABOR=0.0); read: invoice_date<-Data prenotazione[MEDIUM], line_total<-Importo camere[MEDIUM]; asked: DOMAIN, AMOUNT_BASIS(Importo camere); blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Importo camere' could have been avoided

**`C59_large_year_of_invoices`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'; invoice_tax_amount <- column 'IVA'; invoice_gross_amount <- column 'Totale'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_gross_amount <- column 'Totale' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; invoice_tax_amount <- column 'IVA' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 7 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, LABOR=0.507, BOOKINGS=0.312); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH], invoice_tax_amount<-IVA[HIGH], invoice_gross_amount<-Totale[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`CO02_payment_schedule_not_a_register`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected costs, detected costs (MEDIUM)
- mapping expected: supplier_name <- column 'Fornitore'; invoice_number <- column 'N. fattura'; due_date <- column 'Scadenza'; invoice_gross_amount <- column 'Importo da pagare'
- mapping observed: due_date <- column 'Scadenza' [HIGH]; invoice_number <- column 'N. fattura' [HIGH]; net_amount <- column 'Importo da pagare' [MEDIUM]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: AMOUNT_BASIS
- confidence: kind MEDIUM; fields 3 HIGH, 1 MEDIUM
- why: level MANUAL; kind COSTS/MEDIUM (COSTS=0.54, BOOKINGS=0.385, LABOR=0.253); read: supplier_name<-Fornitore[HIGH], invoice_number<-N. fattura[HIGH], due_date<-Scadenza[HIGH], line_total<-Importo da pagare[MEDIUM]; asked: AMOUNT_BASIS(Importo da pagare); blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Importo da pagare' could have been avoided

**`CO03_cost_centre_and_department_columns`** - FIELD_MISSED, FIELD_WRONG, QUESTION_UNNECESSARY (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (MEDIUM)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'Doc.'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; net_amount <- column 'Netto'
- mapping observed: cost_category <- column 'Centro di costo' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Netto' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind MEDIUM; fields 4 HIGH, 1 MEDIUM
- why: level MANUAL; kind COSTS/MEDIUM (COSTS=0.704, LABOR=0.507, BOOKINGS=0.282); read: invoice_date<-Data[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Centro di costo[MEDIUM], line_total<-Netto[HIGH]; asked: VALUE_LABELS; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: invoice_number not recognised
  - FIELD_WRONG [P1]: cost_category claimed from column 'Centro di costo' [MEDIUM], a column that must stay out of the import
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about CC0, CC1, CC2, CC3, CC4, CC5, CC6, CC7, CC8, CC9 could have been avoided

**`CO04_vat_register_two_rates_two_dates`** - FIELD_WRONG, UNSAFE_IMPORT (P0)
- card: costs - truth says: NOT_AUTOMATIC - NINFA: READY (automatic)
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data doc.'; invoice_number <- column 'N. doc.'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; invoice_gross_amount <- column 'Totale doc.'
- mapping observed: invoice_date <- column 'Data doc.' [HIGH]; invoice_gross_amount <- column 'Totale doc.' [MEDIUM]; invoice_number <- column 'N. doc.' [HIGH]; invoice_tax_amount <- column 'IVA 22%' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile 22%' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 6 HIGH, 1 MEDIUM
- why: level READY; kind COSTS/HIGH (COSTS=0.82, LABOR=0.253, BOOKINGS=0.18); read: invoice_date<-Data doc.[HIGH], invoice_number<-N. doc.[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], line_total<-Imponibile 22%[HIGH], invoice_tax_amount<-IVA 22%[HIGH], invoice_gross_amount<-Totale doc.[MEDIUM]
  - FIELD_WRONG [P0]: net_amount decided without asking (column 'Imponibile 22%' [HIGH]); the document does not say
  - UNSAFE_IMPORT [P0]: offered as automatic, but the document needs a person

**`CO05_cash_book_not_invoices`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: invoice_date <- column 'Data' [HIGH]; line_description <- column 'Descrizione' [HIGH]
- questions expected: none - asked: DOMAIN
- confidence: kind LOW; fields 2 HIGH
- why: level MANUAL; read: invoice_date<-Data[HIGH], line_description<-Descrizione[HIGH]; asked: DOMAIN; blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided

**`CO06_utilities_summary_without_number_or_supplier`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: due_date <- column 'Scadenza' [HIGH]; net_amount <- column 'Importo' [MEDIUM]
- questions expected: none - asked: DOMAIN, AMOUNT_BASIS
- confidence: kind LOW; fields 1 HIGH, 1 MEDIUM
- why: level MANUAL; read: line_total<-Importo[MEDIUM], due_date<-Scadenza[HIGH]; asked: DOMAIN, AMOUNT_BASIS(Importo); blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: AMOUNT_BASIS on 'Importo' could have been avoided

**`CO09_amounts_with_eur_suffix_text`** - FIELD_MISSED (P1)
- card: costs - truth says: READY - NINFA: MANUAL
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. documento'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; net_amount <- column 'Imponibile'
- mapping observed: invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. documento' [HIGH]; line_description <- column 'Descrizione' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: none
- confidence: kind HIGH; fields 4 HIGH
- why: level MANUAL; kind COSTS/HIGH (COSTS=0.656, BOOKINGS=0.282, LABOR=0.253); read: invoice_date<-Data[HIGH], invoice_number<-N. documento[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH]; blocked: MISSING_REQUIRED
  - FIELD_MISSED [P1]: net_amount not recognised

**`CO12_attachment_and_approval_columns`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: READY - NINFA: ASK
- kind of data: expected costs, detected costs (HIGH)
- mapping expected: invoice_date <- column 'Data'; invoice_number <- column 'N. fattura'; supplier_name <- column 'Fornitore'; line_description <- column 'Descrizione'; cost_category <- column 'Categoria'; net_amount <- column 'Imponibile'
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]; invoice_date <- column 'Data' [HIGH]; invoice_number <- column 'N. fattura' [HIGH]; line_description <- column 'Descrizione' [HIGH]; net_amount <- column 'Imponibile' [HIGH]; supplier_name <- column 'Fornitore' [HIGH]
- questions expected: none - asked: VALUE_LABELS
- confidence: kind HIGH; fields 5 HIGH, 1 MEDIUM
- why: level ASK; kind COSTS/HIGH (COSTS=0.82, LABOR=0.507, BOOKINGS=0.282); read: invoice_date<-Data[HIGH], invoice_number<-N. fattura[HIGH], supplier_name<-Fornitore[HIGH], line_description<-Descrizione[HIGH], cost_category<-Categoria[MEDIUM], line_total<-Imponibile[HIGH]; asked: VALUE_LABELS
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

**`CO13_category_by_month_matrix_not_a_register`** - QUESTION_UNNECESSARY (P2)
- card: costs - truth says: REJECT - NINFA: MANUAL
- kind of data: expected other, detected other (LOW)
- mapping expected: -
- mapping observed: cost_category <- column 'Categoria' [MEDIUM]
- questions expected: none - asked: DOMAIN, VALUE_LABELS
- confidence: kind LOW; fields 1 MEDIUM
- why: level MANUAL; read: cost_category<-Categoria[MEDIUM]; asked: DOMAIN, VALUE_LABELS; blocked: MISSING_REQUIRED
  - QUESTION_UNNECESSARY [P2]: DOMAIN could have been avoided
  - QUESTION_UNNECESSARY [P2]: VALUE_LABELS about Colazioni could have been avoided

## Appendix B - the corpus

| Document | Card | Truth says | NINFA | Tags |
|---|---|---|---|---|
| `L01_csv_basic` | labor | READY | READY | - |
| `L02_xlsx_giorno_area` | labor | READY | READY | office |
| `L03_alias_settore_pianificate_lavorate` | labor | READY | READY | - |
| `L04_alias_dept_hprev_consuntivo` | labor | READY | ASK | - |
| `L05_english_planned_actual` | labor | READY | READY | - |
| `L06_english_scheduled_worked` | labor | READY | READY | - |
| `L07_reparto_slash_mansione_ore_prog` | labor | READY | READY | - |
| `L08_reparto_o_mansione_with_hourly_rate` | labor | READY | READY | - |
| `L09_centro_operativo` | labor | READY | ASK | - |
| `L10_only_planned_hours` | labor | READY | READY | - |
| `L11_only_actual_hours` | labor | READY | READY | - |
| `L12_reordered_with_junk_columns` | labor | READY | READY | office |
| `L13_title_block_before_table` | labor | READY | READY | - |
| `L14_summary_block_before_table` | labor | READY | READY | - |
| `L15_summary_block_after_table` | labor | READY | READY | - |
| `L16_total_row_correct` | labor | READY | READY | - |
| `L17_subtotals_per_department` | labor | READY | READY | - |
| `L18_sheet_per_department` | labor | READY | ASK | - |
| `L19_title_names_the_department` | labor | READY | ASK | - |
| `L20_department_as_section_lines` | labor | READY | READY | - |
| `L21_sections_with_totals_and_notes` | labor | READY | READY | office |
| `L22_two_level_header` | labor | READY | READY | - |
| `L23_two_level_header_hours_over_planned_actual` | labor | READY | ASK | office |
| `L24_duplicate_ore_columns` | labor | ASK | ASK | - |
| `L25_near_duplicate_hours_headers` | labor | ASK | READY | - |
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
| `L39_known_italian_department_words` | labor | READY | ASK | - |
| `L40_vocabulary_restaurant_bar_governante` | labor | READY | ASK | - |
| `L41_pii_split_name_email_phone_taxcode` | labor | READY | READY | - |
| `L42_pii_name_and_company_email` | labor | READY | ASK | office |
| `L43_dates_us_provable` | labor | READY | READY | - |
| `L44_dates_ambiguous_day_month` | labor | ASK | ASK | negative |
| `L45_dates_weekday_prefix_text` | labor | READY | BLOCKED | - |
| `L46_dates_dotted_text_hours_comma` | labor | READY | READY | - |
| `L47_rates_and_costs_columns` | labor | READY | READY | - |
| `L48_two_comparable_tables_two_weeks` | labor | ASK | ASK | - |
| `L49_decoy_legend_table_before_real_one` | labor | READY | READY | - |
| `L50_hidden_draft_sheet_and_visible_sheet` | labor | READY | READY | adversarial |
| `L51_summary_sheet_first_then_detail` | labor | READY | READY | - |
| `L52_dashboard_sheet_and_data_sheet` | labor | READY | READY | office |
| `L53_header_on_row_nine_after_long_preamble` | labor | READY | READY | office |
| `L54_office_weekly_roster_final` | labor | READY | ASK | office |
| `L55_office_monthly_hours_report` | labor | READY | READY | office |
| `L56_office_front_desk_roster_csv` | labor | READY | ASK | office |
| `L57_office_kitchen_and_restaurant_two_sheets` | labor | READY | MANUAL | office |
| `L58_office_names_in_two_columns_and_comments` | labor | READY | ASK | office |
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
| `L69_adv_very_long_cell_and_odd_headers` | labor | READY | ASK | adversarial |
| `L70_adv_example_table_before_real_table` | labor | READY | READY | adversarial |
| `L71_adv_total_word_inside_a_department` | labor | ASK | ASK | adversarial |
| `L72_large_three_months_roster` | labor | READY | READY | large |
| `LO01_reception_roster_bare_ore_title_department` | labor | ASK | ASK | office |
| `LO02_payroll_monthly_summary_by_qualifica` | labor | REJECT | BLOCKED | office, negative |
| `LO03_clock_in_out_times_no_hours` | labor | REJECT | MANUAL | office, negative |
| `LO04_weekday_name_and_date_in_two_columns` | labor | READY | READY | office |
| `LO05_future_days_have_no_actual_hours_yet` | labor | READY | READY | office |
| `LO06_job_titles_in_qualifica_column` | labor | READY | ASK | office |
| `LO07_department_in_a_label_value_block` | labor | READY | ASK | office |
| `LO08_one_sheet_per_week_sett43_sett44` | labor | READY | READY | office |
| `LO09_legend_block_drawn_beside_the_table` | labor | READY | READY | office |
| `LO10_header_repeated_in_every_department_block` | labor | NOT_AUTOMATIC | ASK | office, negative |
| `LO11_department_cells_merged_down_the_column` | labor | READY | READY | office |
| `LO12_blank_row_between_every_record` | labor | READY | READY | office |
| `LO13_hours_written_with_a_unit` | labor | READY | MANUAL | office |
| `LO14_header_cells_with_line_breaks` | labor | READY | READY | office |
| `LO15_abbreviated_department_header_and_codes` | labor | READY | ASK | office |
| `LO16_extra_numeric_columns_overtime_leave` | labor | READY | READY | office |
| `B01_csv_italian_canonical` | bookings | READY | ASK | - |
| `B02_npren_prenotato_il_dal_al` | bookings | READY | ASK | - |
| `B03_english_booking_id_created_source` | bookings | NOT_AUTOMATIC | MANUAL | - |
| `B04_english_reservation_id_creation_date` | bookings | READY | ASK | - |
| `B05_confirmation_booked_at_accommodation` | bookings | NOT_AUTOMATIC | MANUAL | - |
| `B06_ref_portale_totale_soggiorno` | bookings | READY | MANUAL | - |
| `B07_room_revenue_and_total_stay_both` | bookings | READY | ASK | - |
| `B08_abbreviated_headers` | bookings | READY | MANUAL | - |
| `B09_mixed_italian_english_headers` | bookings | READY | ASK | office |
| `B10_guest_name_email_phone_notes` | bookings | READY | ASK | - |
| `B11_guest_column_holds_names_not_a_count` | bookings | READY | ASK | - |
| `B12_guests_count_column_and_guest_name` | bookings | READY | ASK | - |
| `B13_pax_and_num_ospiti` | bookings | READY | ASK | - |
| `B14_booker_and_guest_names_two_columns` | bookings | READY | ASK | - |
| `B15_title_before_table` | bookings | READY | ASK | - |
| `B16_notes_below_the_table` | bookings | READY | ASK | - |
| `B17_summary_block_before_table` | bookings | READY | ASK | - |
| `B18_totals_row_and_channel_subtotals` | bookings | READY | READY | - |
| `B19_dashboard_bookings_and_legend_sheets` | bookings | READY | ASK | - |
| `B20_sheet_per_month_same_columns` | bookings | READY | ASK | - |
| `B21_two_tables_confirmed_and_cancelled` | bookings | ASK | ASK | - |
| `B22_status_and_cancellation_date` | bookings | READY | ASK | - |
| `B23_status_modificata_is_ambiguous` | bookings | ASK | ASK | - |
| `B24_channels_direct_phone_email_walkin` | bookings | READY | ASK | - |
| `B25_ota_channels_with_commission_columns` | bookings | READY | READY | - |
| `B26_amounts_thousands_dot_comma_decimal` | bookings | READY | READY | - |
| `B27_amounts_point_decimal_csv` | bookings | READY | ASK | - |
| `B28_amounts_with_euro_sign_text` | bookings | READY | ASK | - |
| `B29_amounts_excel_currency_format` | bookings | READY | ASK | - |
| `B30_dates_text_italian` | bookings | READY | ASK | - |
| `B31_dates_us_provable_csv` | bookings | READY | ASK | - |
| `B32_dates_ambiguous_day_month` | bookings | ASK | ASK | negative |
| `B33_dates_dotted_and_day_month_name` | bookings | READY | ASK | - |
| `B34_dates_day_month_name_text` | bookings | READY | MANUAL | - |
| `B35_booking_timestamp_with_time` | bookings | READY | ASK | - |
| `B36_two_level_header` | bookings | READY | ASK | - |
| `B37_duplicate_date_columns` | bookings | NOT_AUTOMATIC | MANUAL | negative |
| `B38_reordered_columns_with_junk` | bookings | READY | ASK | - |
| `B39_ids_with_leading_zeros_and_numeric` | bookings | READY | ASK | - |
| `B40_office_pms_export_colored_header` | bookings | READY | MANUAL | office |
| `B41_office_channel_manager_extract` | bookings | READY | MANUAL | office |
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
| `B60_adv_hidden_sheet_with_older_bookings` | bookings | READY | ASK | adversarial |
| `B61_adv_instructions_in_guest_notes` | bookings | READY | ASK | adversarial |
| `B62_adv_formulas_and_html_in_cells` | bookings | READY | ASK | adversarial |
| `B63_adv_total_word_in_a_notes_column` | bookings | READY | ASK | adversarial |
| `B64_adv_near_identical_date_headers` | bookings | NOT_AUTOMATIC | ASK | adversarial |
| `B65_adv_very_long_cells_and_unicode` | bookings | READY | ASK | adversarial |
| `B66_large_year_of_bookings` | bookings | READY | ASK | large |
| `BO01_channel_written_as_codes` | bookings | READY | MANUAL | office |
| `BO02_arrivals_by_day_sections_no_ids` | bookings | REJECT | MANUAL | office, negative |
| `BO03_channel_manager_abbreviations` | bookings | READY | MANUAL | office |
| `BO04_front_desk_arrivals_list_no_booking_date` | bookings | REJECT | MANUAL | office, negative |
| `BO05_kpi_block_beside_the_table` | bookings | READY | ASK | office |
| `BO06_table_starts_in_column_c_frozen_panes` | bookings | READY | ASK | office |
| `BO07_weekday_prefixed_dates` | bookings | READY | MANUAL | office |
| `BO08_room_and_breakfast_revenue_columns` | bookings | READY | ASK | office |
| `BO09_status_written_as_ok_canc_ns` | bookings | READY | ASK | office |
| `BO10_one_sheet_per_week` | bookings | READY | ASK | office |
| `BO11_header_cells_with_line_breaks` | bookings | READY | ASK | office |
| `BO12_channel_merged_down_the_column` | bookings | READY | READY | office |
| `BO13_blank_row_between_every_record` | bookings | READY | ASK | office |
| `BO14_two_months_side_by_side` | bookings | NOT_AUTOMATIC | MANUAL | office, negative |
| `C01_complete_register_consistent` | costs | READY | ASK | - |
| `C02_english_amount_excl_vat` | costs | READY | MANUAL | - |
| `C03_totale_netto_imposta_totale` | costs | READY | READY | - |
| `C04_imponibile_iva_lordo` | costs | READY | READY | - |
| `C05_net_vat_gross_amount_english` | costs | READY | MANUAL | - |
| `C06_netto_only` | costs | READY | READY | - |
| `C07_imponibile_only` | costs | READY | MANUAL | - |
| `C08_net_vat_total_do_not_add_up` | costs | WARN | READY | negative |
| `C09_single_amount_column_importo` | costs | ASK | ASK | - |
| `C10_only_totale_may_be_gross` | costs | ASK | MANUAL | negative |
| `C11_only_gross_stated_vat_included` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C12_neg_without_document_number` | costs | REJECT | MANUAL | negative |
| `C13_neg_without_description` | costs | REJECT | MANUAL | negative |
| `C14_neg_without_supplier` | costs | REJECT | MANUAL | negative |
| `C15_neg_without_date` | costs | REJECT | MANUAL | negative |
| `C16_eight_known_categories` | costs | READY | ASK | - |
| `C17_everyday_category_words_luce_acqua_gas` | costs | READY | READY | - |
| `C18_unknown_category_words` | costs | ASK | ASK | - |
| `C19_no_category_column` | costs | READY | READY | - |
| `C20_title_before_table` | costs | READY | ASK | office |
| `C21_total_row_correct` | costs | READY | READY | - |
| `C22_summary_block_before_table` | costs | READY | READY | - |
| `C23_subtotals_per_category` | costs | READY | READY | - |
| `C24_summary_sheet_and_register_sheet` | costs | READY | ASK | - |
| `C25_supplier_directory_sheet_and_invoices_sheet` | costs | READY | READY | - |
| `C26_sheet_per_month_same_columns` | costs | READY | READY | - |
| `C27_dates_text_italian` | costs | READY | READY | - |
| `C28_dates_iso_csv` | costs | READY | READY | - |
| `C29_dates_ambiguous_us_or_italian` | costs | ASK | ASK | negative |
| `C30_amounts_italian_thousands` | costs | READY | READY | - |
| `C31_amounts_us_thousands_csv` | costs | READY | READY | - |
| `C32_amounts_euro_sign_text` | costs | READY | READY | - |
| `C33_credit_notes_negative_amounts` | costs | READY | ASK | - |
| `C34_currency_symbol_and_codes` | costs | READY | READY | - |
| `C35_no_currency_column` | costs | READY | READY | - |
| `C36_document_number_styles` | costs | READY | READY | - |
| `C37_vat_number_and_due_date_columns` | costs | READY | READY | - |
| `C38_several_lines_per_invoice` | costs | READY | ASK | - |
| `C39_total_word_inside_a_description` | costs | READY | READY | adversarial |
| `C40_two_level_header_importi` | costs | READY | MANUAL | - |
| `C41_duplicate_importo_columns` | costs | NOT_AUTOMATIC | ASK | negative |
| `C42_near_identical_net_headers` | costs | NOT_AUTOMATIC | READY | adversarial |
| `C43_reordered_with_junk_columns` | costs | READY | ASK | - |
| `C44_office_accounting_export_header_on_row_five` | costs | READY | ASK | office |
| `C45_office_cost_ledger_csv_semicolon` | costs | READY | MANUAL | office |
| `C46_office_manual_expense_sheet` | costs | READY | MANUAL | office |
| `C47_office_supplier_invoices_with_notes` | costs | READY | MANUAL | office |
| `C48_neg_bank_statement` | costs | REJECT | MANUAL | negative |
| `C49_neg_payroll_with_names` | costs | REJECT | MANUAL | negative |
| `C50_neg_staff_roster_on_costs_card` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C51_neg_bookings_on_costs_card` | costs | NOT_AUTOMATIC | MANUAL | negative |
| `C52_neg_empty_register` | costs | REJECT | BLOCKED | negative |
| `C53_neg_mixed_date_formats` | costs | NOT_AUTOMATIC | BLOCKED | negative |
| `C54_neg_costs_and_revenues_two_tables` | costs | ASK | ASK | negative |
| `C55_adv_hidden_sheet_with_other_invoices` | costs | READY | READY | adversarial |
| `C56_adv_instructions_in_descriptions` | costs | READY | READY | adversarial |
| `C57_adv_formulas_html_and_unicode` | costs | READY | READY | adversarial |
| `C58_adv_very_long_description_cell` | costs | READY | READY | adversarial |
| `C59_large_year_of_invoices` | costs | READY | ASK | large |
| `CO01_protocol_number_and_supplier_document_number` | costs | READY | READY | office |
| `CO02_payment_schedule_not_a_register` | costs | REJECT | MANUAL | office, negative |
| `CO03_cost_centre_and_department_columns` | costs | READY | MANUAL | office |
| `CO04_vat_register_two_rates_two_dates` | costs | NOT_AUTOMATIC | READY | office, negative |
| `CO05_cash_book_not_invoices` | costs | REJECT | MANUAL | office, negative |
| `CO06_utilities_summary_without_number_or_supplier` | costs | REJECT | MANUAL | office, negative |
| `CO07_supplier_written_as_section_lines` | costs | REJECT | MANUAL | office, negative |
| `CO08_supplier_cells_merged_down_the_column` | costs | READY | READY | office |
| `CO09_amounts_with_eur_suffix_text` | costs | READY | MANUAL | office |
| `CO10_header_cells_with_line_breaks` | costs | READY | READY | office |
| `CO11_blank_row_between_every_record` | costs | READY | READY | office |
| `CO12_attachment_and_approval_columns` | costs | READY | ASK | office |
| `CO13_category_by_month_matrix_not_a_register` | costs | REJECT | MANUAL | office, negative |
