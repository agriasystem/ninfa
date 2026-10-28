# 0035 — How a family is read belongs to the family

## Context

ADR 0034 made a source remember several recurring families. It left one thing as it was: *how a document is read* - which sheets,
which hours a day grid holds, where the department comes from - lived in the profile's `format_options.layout`, which is written by
**the last import**. With one structure per source that is the source's. With several it is whichever family happened to come last,
and it was applied to a file **before** anyone knew whose file it was.

The order of the pipeline, measured:

```
upload -> scan_workbook (raw, neutral)
       -> the layout saved by the LAST import (_base_layout)
       -> understand(scan, base): `base.sheets` restricts which sheets are analysed
       -> candidate tables, the table chosen
       -> family matching            <- only here
       -> grid / department applied, meaning of the columns, validation
```

Reproduced on the code of ADR 0034 (same property, same kind of data, real files):

| Sequence | Result |
|---|---|
| bookings xlsx A (sheet `Prenotazioni`) -> xlsx B (sheet `Export`) -> A | A: `BLOCKED / NO_TABLE` (B's `sheets` replaced A's) |
| xlsx A (sheet chosen) -> csv B | B: `BLOCKED / NO_TABLE` (a csv's one sheet is called `""`); the csv could not even be taught |
| csv B -> xlsx A (sheet chosen) -> csv B | B: `BLOCKED / NO_TABLE` |
| staff day grid A -> ordinary table B -> A | A asks `GRID_HOURS` again (B's import left `{}`) |

## What is the family's and what is common

`format_options` of a profile, and who reads what in the understanding flow:

| Part | Read by the flow | Belongs to |
|---|---|---|
| `layout.sheets` (the sheet the person chose) | `_base_layout` -> which sheets are analysed | **family** |
| `layout.grid` (hours of a day grid) | `plan_labor` (the hours when the file does not say) | **family** |
| `layout.department` (SECTION / SHEET / TITLE) | the table the layout makes; the department confirmation | **family** |
| `date_order`, `decimal_style`, `amount_basis`, `department_value` | already `Memory.answers` | family (ADR 0033) |
| `date_formats`, `decimal_separator`, `thousands_separator`, `sheet_name` | only the profile's prefill, the "recognised profile" shortcut and the legacy `mapping: null` import | the profile's last import (see limits) |
| `delimiter`, `encoding` | never written by Smart Import V3: detected on every file | nobody |
| `status_mapping`, `channel_mapping`, `role_mapping`, `category_mapping` | the words the person taught NINFA | **property + kind of data** (the hotel's vocabulary) |

Only the first three were wrong to share. The dictionaries of words stay common on purpose: a word means the same in every file of a
hotel, and a second family should not have to be taught it again.

## Decision

1. **Reading hints live in the family** (`Memory.layout`, JSON in `format_options.learning`; no table, no column, **no migration**): the
   `LayoutSpec` the profile saves, without any date or row (`for_profile`). `None` is "not known" (a family remembered before this
   decision), `{}` is "read with the layout reader and nothing special". A hint is saved only after a person confirmed the family.
   Sheet names are structure, but one that looks like a person, an address or a long number is never kept.

2. **The pipeline recognises first, then reads.**
   * **A.** The document on its own terms: only what the person says *now* decides how it is read. The layout of the last import is
     applied to nothing.
   * **B.** Which family is it? Every candidate table of the document is compared with the source's families (unchanged matching and
     ambiguity rule of ADR 0034). If the table the ranking chose is not a family's but exactly one other table of the document is
     clearly one (nothing it remembers is lost), that is the table the person taught.
   * **C.** Only a family recognised for sure - taught by a person, nothing remembered lost - lends its hints. If they involve a
     sheet, the document is read again through it, and the hints are accepted only if that reading is *the same family again*;
     otherwise they are dropped and the document stays as read in A. No guessing.
   * **D.** Meaning of the columns and validation, as ever.
   If two families could be the file (ADR 0034) no family is chosen, so no hint is lent: the file is read on its own terms.

3. **What a family remembers is what its file HAS.** A column a layout adds (the date and hours of a day grid, the department of a
   title) does not exist in the file as read plainly, so it could never be found there: the remembered matching keeps only the
   columns of the plain table, and the days and totals of a grid (which name the week, not the source) are left out of its structure.
   Without this a grid or title family was never recognised at all, and only the last-import layout kept it working.

4. **A department confirmed from the title is an answer** for that family: the next file whose title still names one department is
   read without asking again (the department itself is read from the title every time).

5. **Legacy.** A family stored without hints reads with the profile's layout only if it is the family the profile's saved matching
   belongs to (`Learning.current`): that layout *is* its own last import's. For any other family it is nothing. A profile that
   remembers no family at all gives no hints: a source nobody confirmed is read on its own terms and asks what it asks.

6. **Local.** Confirming a family replaces its hints and nobody else's (a new revision, the old hints in *that family's* history;
   not a new family). A confirmation from a file with no sheets (a csv) leaves the sheet chosen for the same family's xlsx alone.
   Family and revision caps are unchanged and separate.

## Consequences

* A source can keep an xlsx on one sheet, another xlsx on another, a csv, a day grid and a department-in-the-title document, each read
  as it was taught whatever came in between; measured by the multi-format extension of the Source Learning Benchmark V1.
* A source nobody taught yet is no longer read through the sheet/grid of some other import. The price: a profile saved before Source
  Learning (no `learning`) loses its layout hints and asks once more (the same price ADR 0033 already named).
* Limits, stated rather than hidden:
  * Two structures that differ only in a layout choice the file does not show are one family; the last confirmation wins (with
    history). They cannot be told apart by anything in the file.
  * The profile's saved column matching, `date_formats`, `decimal_separator` and `sheet_name` are still the last import's. They feed
    the legacy "recognised profile" status the page shows (`profile.status`, which therefore reads `NEEDS_REVIEW` for a returning
    family that is not the last one) and the legacy import with `mapping: null`; the understanding flow does not use them for a
    family that did not write them.
  * A `table_key` answer (which of several tables) is still never saved: a workbook that needs that question asks it every time.
  * A grid is recognised by what is *not* its days: its identity is thin (the person column and what is next to it).
