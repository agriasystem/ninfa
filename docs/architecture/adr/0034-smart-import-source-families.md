# 0034 — A source remembers several recurring families

## Context

ADR 0033 made Smart Import remember what a person confirmed about a source and ask less the next time. It kept **one** memory per
source (property + kind of data): the structure of the last confirmed file. A hotel does not bring one file. In the same kind of data
it brings back the PMS export, an OTA export, an internal report - none of them the same structure, all of them recurring.

Measured on the code of ADR 0033 (same property, same kind of data, a person teaches A, then B, then A comes back): A is
`MAJOR_CHANGE`, nothing is reused and the person is asked all over again - in bookings, staff and costs alike. Teaching B **replaced**
A. A source that alternates between two structures would be asked every single time.

## Decision

1. **A source holds N families.** The `learning` section in the profile's `format_options` (JSON; still no table, no column, **no
   migration**) becomes `{v: 2, seq, current, families: [Memory, ...]}`. A family is exactly the `Memory` of ADR 0033 (structure with
   the class of its values, confirmed mapping, the part a person decided, closed answers, revision, history, fingerprint) plus a stable
   `id` and a `touched` tick. A section written before there were families (one flat memory) is read as a source with one family; a
   damaged family is left out and the others survive.

2. **Family and revision are different things.**
   * A **revision** is the same family evolving: the file still holds *everything the family remembers* - the same columns, moved,
     renamed to what the engine reads the same, with new ones, or one whose meaning the person now corrects. A confirmation updates
     that family (a new revision when its meaning changed; the old one stays in that family's history).
   * A **family** is another structure that recurs next to it. As soon as a remembered column is no longer in the file - gone, or called
     something else - the file is a structure of its own and a confirmation starts a new family. The asymmetry is deliberate: a family
     too many costs a record; a family too few loses the one that was there (the very defect above).

3. **Which family is this file?** The file is matched against **every** family of the source (`match_source`, unchanged: column by
   column, the current document always wins). A family is chosen only if it explains the file *clearly better* than any other that
   could be it. The measure is the **residual**: columns the family does not explain as they are (new, missing, contradicted, or held
   only under another name). The winner must explain the file completely (residual 0) or leave at least `MIN_RESIDUAL_GAP = 2` columns
   fewer unexplained than the runner-up. Otherwise **nothing is chosen and nothing is reused**: the person is asked as for a source
   nobody taught. Two lookalikes (`Data | Prev. | Eff. | Area` / `... | Costo`) are told apart by what the file contains, never by a
   weak coincidence; a file that could be either is never settled by a guess. Where the engine reads a renamed header as the same
   field, that is evidence, but weaker than the header itself.

4. **Correction is local.** A confirmation changes the one family the server found the file to be a revision of (or adds one). It
   never rewrites another. Trust rules of ADR 0033 are unchanged and per family; the engine alone never writes once a person has
   confirmed anything in the source.

5. **The profile's saved matching stays "the last import"** (it is the legacy shortcut for a source read before). It is applied only to a
   file of the family whose import wrote it (`Learning.current`); a file of another family is read from its own family, even when the
   saved matching of the profile would *fit* it. Being recognised as a family that a person taught also releases the "this document
   does not say what kind of data it is" hold, as a recognised profile always did.

6. **Limits, each its own.** `FAMILIES_KEPT = 32` families per source and `HISTORY_KEPT = 5` revisions per family. A hotel has a
   handful of recurring files per kind of data and a busy one a few dozen (an export per supplier, per OTA, per outlet); 32 is far
   above that, matching a file against all of them is a few milliseconds, and the section stays within ~200 KB. Past the limit the
   least useful go first - those only the engine read, then the longest unused - never the family just written; a dropped family is
   simply taught once more.

7. **Scope is unchanged:** property + kind of data are the source's; a family never crosses either. Nothing personal is kept in any
   family and a family's identity is a counter, never a file name.

## Consequences

* A source alternating between structures is recognised every time, in any order (A→B→A, A→B→C→A→C→B, a drifted A after B and C),
  with nothing asked again; measured by the multi-source extension of the Source Learning Benchmark V1.
* A new structure that is a lookalike of a known one costs one confirmation and one record, and never costs the known one.
* A file that could be either of two families asks - one question more is the price of never reading a file with the wrong family.
* Known limit: structures nested in each other (a family whose columns are all inside a larger one) are not told apart by the
  smaller one's own columns alone. If the larger is taught after the smaller, it is a revision of it (nothing remembered is lost) and
  the smaller then reads as the larger with optional columns missing: what it holds is reused, nothing is applied that the file does
  not prove. The other order keeps both.
* Known limit: the layout of a document (sheet, day grid, department of all the rows) is still the profile's - the last import's - and
  a day grid is not matched by its synthetic columns.
* No screen yet says "Sorgente riconosciuta"; `FileInspection.learning` stays internal.
