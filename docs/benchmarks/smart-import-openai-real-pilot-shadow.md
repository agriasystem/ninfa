# Smart Import - OpenAI - Real pilot SHADOW validation

Date 2026-11-16 - model `gpt-6.1-sol`, reasoning `low`, mode `shadow`, vocabulary certainty `False`.

> **There are no real hotel files in this environment.** What exists is the 28 files of the demo (`tests/fixtures`: the golden scenario of Masseria Ninfa and the format variants the importers were built against), none of them from a customer. The database keeps no copy of an uploaded file (a hash and a size), and no spreadsheet of any pilot hotel is in the repository. Nothing external was introduced. This is therefore a validation of the RUNTIME PATH on the files that exist, not of the model on a hotel's own exports.

## Corpus

28 files, all CSV: bookings 15, costs 13 (staff: none exists). 982 rows in all, median 3 per file, **20 files with 3 rows or fewer**. Sources: the demo's golden files (canonical Italian headers), and format variants (English / Italian headers, `;` and `,`, BOM, CP1252, personal columns). Known sources: none taught (see Source Learning).

## Privacy

* **Preflight, before the first real request**: every request the 28 files can produce was built with no network and audited with the gate forced open (9 requests): only the closed evidence (largest 2790 characters), no file name, no row, 1832 personal values of the files looked for (found WITHOUT the engine, from the headers and the shapes): **0 found**.
* **It first FOUND one** and stopped: a column of street addresses under the header "Street" was sent as an example value (addresses were recognised by header words only). Fixed in the rules (`pii.py`: street words, the shape of an address); covered by tests.
* **Live traffic** (probe, 26 requests): `store=false`, strict Structured Output, no tool, no identifier, the model asked for: every check passed; the same audit as the preflight on each request: 0 violations.
* **Browser**: personal values on any screen, rules and SHADOW: 0.
* Not kept: the key, a request, an answer, the vendor's request ids.

## Deterministic vs SHADOW (production gate)

**The model was asked about 0 of 28 files.** The gate saw nothing it could help with: where the rules ask, they ask about a column they already placed (a date order, a basis, an identifier), not about one they could not read. The SHADOW screen was the rules' own in 28 of 28 files.

| File | Rows | Rules | ASSIST would show | Model asked |
|---|---:|---|---|---|
| `bookings/ambiguous_dates.csv` | 2 | ASK (1 q) | ASK (1 q) | no |
| `bookings/changed_schema.csv` | 1 | MANUAL (0 q) | MANUAL (0 q) | no |
| `bookings/cp1252.csv` | 2 | MANUAL (0 q) | MANUAL (0 q) | no |
| `bookings/duplicate_source_id.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `bookings/en_comma.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `bookings/invalid_row.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `bookings/it_semicolon.csv` | 3 | READY (0 q) | READY (0 q) | no |
| `bookings/masseria_ninfa_bookings_v1.csv` | 16 | READY (0 q) | READY (0 q) | no |
| `bookings/pii_unmapped_columns.csv` | 2 | MANUAL (0 q) | MANUAL (0 q) | no |
| `bookings/unknown_status.csv` | 2 | ASK (1 q) | ASK (1 q) | no |
| `bookings/utf8_bom.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `costs/invoices/software.csv` | 11 | ASK (2 q) | ASK (2 q) | no |
| `costs/masseria_ninfa_cost_bookings_v1.csv` | 492 | READY (0 q) | READY (0 q) | no |
| `expected/masseria_ninfa_bookings_history_v1.csv` | 252 | READY (0 q) | READY (0 q) | no |
| `invoices/golden/masseria_ninfa_cost_06_structured.csv` | 13 | ASK (1 q) | ASK (1 q) | no |
| `invoices/golden/masseria_ninfa_cost_08_xlsx_rows.csv` | 5 | READY (0 q) | READY (0 q) | no |
| `invoices/structured/category_mapped.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `invoices/structured/changed_schema.csv` | 1 | ASK (1 q) | ASK (1 q) | no |
| `invoices/structured/conflicting_repeated_total.csv` | 2 | MANUAL (0 q) | MANUAL (0 q) | no |
| `invoices/structured/cp1252.csv` | 3 | ASK (3 q) | ASK (3 q) | no |
| `invoices/structured/duplicate_line_number.csv` | 2 | MANUAL (0 q) | MANUAL (0 q) | no |
| `invoices/structured/en_comma.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `invoices/structured/it_semicolon.csv` | 3 | ASK (3 q) | ASK (3 q) | no |
| `invoices/structured/pii_unmapped_columns.csv` | 1 | MANUAL (0 q) | MANUAL (0 q) | no |
| `invoices/structured/repeated_invoice_header.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `invoices/structured/utf8_bom.csv` | 3 | ASK (1 q) | ASK (1 q) | no |
| `revenue/masseria_ninfa_bookings_revenue_v1.csv` | 138 | READY (0 q) | READY (0 q) | no |
| `snapshots/masseria_ninfa_bookings_addendum_v1.csv` | 7 | READY (0 q) | READY (0 q) | no |

### Probe: the gate forced open (NOT production behaviour)

Asked anyway, so that the model's reading can be seen where the gate would never ask. 9 files have something a model could name; the same SHADOW run, the same audit.

| File | Rules | ASSIST would show | Domain / confidence | Columns named | Outcome |
|---|---|---|---|---:|---|
| `bookings/ambiguous_dates.csv` | ASK (1 q) | ASK (1 q) | BOOKINGS / MEDIUM | 0 | neutral |
| `bookings/changed_schema.csv` | MANUAL (0 q) | MANUAL (0 q) | BOOKINGS / MEDIUM | 0 | neutral |
| `bookings/cp1252.csv` | MANUAL (0 q) | MANUAL (0 q) | BOOKINGS / MEDIUM | 0 | neutral |
| `bookings/pii_unmapped_columns.csv` | MANUAL (0 q) | MANUAL (0 q) | BOOKINGS / MEDIUM | 0 | neutral |
| `bookings/unknown_status.csv` | ASK (1 q) | ASK (1 q) | BOOKINGS / MEDIUM | 0 | neutral |
| `invoices/golden/masseria_ninfa_cost_06_structured.csv` | ASK (1 q) | ASK (2 q) | COSTS / MEDIUM | 1 | useful |
| `invoices/golden/masseria_ninfa_cost_08_xlsx_rows.csv` | READY (0 q) | READY (0 q) | COSTS / MEDIUM | 0 | neutral |
| `invoices/structured/category_mapped.csv` | ASK (1 q) | ASK (1 q) | COSTS / MEDIUM | 0 | neutral |
| `invoices/structured/duplicate_line_number.csv` | MANUAL (0 q) | MANUAL (0 q) | COSTS / MEDIUM | 0 | neutral |

Outcome over all 28 files in the probe: useful 1, neutral 27, wrong but safe 0, potentially unsafe 0.

## Human interaction cost

| | Rules | ASSIST (production gate) | ASSIST (probe) |
|---|---:|---:|---:|
| zero intervention | 25% | 25% | 25% |
| one confirmation | 43% | 43% | 39% |
| several confirmations | 11% | 11% | 14% |
| manual matching | 21% | 21% | 21% |
| blocked | 0% | 0% | 0% |
| confirmations per file | 0.714 | 0.714 | 0.75 |

Manual matching avoidable by ASSIST: 0 (probe), 0 (production). Questions the model would add in the probe: 1 (1 useful, 0 not material).

## Source Learning reuse

Not measurable on these files: with the production gate the model is asked about NONE of them, whether or not a source was learned, so there is no call to avoid. The mechanism is measured where there is something to ask: on 11 families x 7 versions (synthetic), 13 of 55 recognised files asked the model again in V1, 0 in V1.1 ([report](smart-import-openai-assist-v1-1.md)).

## Model stability (probe)

8 files asked 3 times each. Same domain in 8/8, same mapping in 8/8, same ASK/READY/MANUAL in 8/8; oscillations that would change ASK/READY: 0. Differences: 0. (The answers on these files are nearly empty - a model that names nothing is stable by construction: this proves little about a hotel's own columns.)

## Safety

| Indicator | Production gate | Probe |
|---|---:|---:|
| unsafe would-be READY | 0 | 0 |
| wrong-domain would-be READY | 0 | 0 |
| personal values in a request | 0 | 0 |
| personal values in a browser screen | 0 | 0 |
| SHADOW screen different from the rules' own | 0 | 0 |
| Source Learning overwrite / destructive action / scope inferred by the model | 0 | 0 |

(SHADOW persists nothing and no import is run; the contract the model answers has no field for a scope, and its evidence has none.)

## Latency, tokens, cost

| | Production gate | Probe |
|---|---:|---:|
| model calls | 0 | 25 (9 files, 16 repeats) |
| files not asked | 28 | 19 |
| latency p50 / p95 / max | - | 5293 / 17885 / 22968 ms |
| timeouts | 0 | 0 |
| tokens in / out | 0 / 0 | 57166 / 7130 |
| cost at list price | $0 | $0.1856 |

## Limitations

* **No real hotel file.** 28 demo files, 20 of them with 3 rows or fewer: a MANUAL or TO_CHECK verdict on them is largely a consequence of too few values, not of an unreadable header. Nothing here measures what the model does with a hotel's own words.
* No staff/personnel file exists; no XLSX (all CSV); no source was ever learned.
* The "truth" used to judge the model is written by hand for the demo's own headers.
* One model, one reasoning level, few draws.

