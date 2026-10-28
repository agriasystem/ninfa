# 0033 — Smart Import learns sources from what a person confirmed

## Context

Smart Import reads most files, asks about what is ambiguous and lets a person match columns by hand. Each month the same hotel sends the
same kind of file; if it needed an answer once, it needs it every time. A model could "guess" it, but NINFA must not depend on
Anthropic, OpenAI, Gemini or any external API for it, and a guess is not what a hotelier confirmed.

A mapping profile already existed (one per data source, in the property's own scope), but it was believed on the strength of header
names alone, could not tell a person's confirmation from the engine's own reading, was overwritten by the next import and could not be
partly reused.

## Decision

1. **Evolve the existing profile; do not build a second system.** A small `learning` section lives in the profile's `format_options`
   JSON: the structure of the last confirmed file (header keys + classes of values, personal-data columns as a placeholder), the
   confirmed mapping, the part a person decided, closed answers and a short history. No table, no column, **no migration**; a
   damaged or newer section is just "no memory".

2. **Only a person makes a memory trusted** - an explicit answer that decided something the engine had not read clearly, or a
   matching built by hand and imported. The engine's own READY leaves ENGINE evidence that is never used to skip a question and never
   replaces a person's confirmation. The server knows how a decision was confirmed; the client cannot claim it. The person's
   "remember" box is respected.

3. **A memory is evidence, never authority.** It is applied column by column, as if the person had answered again, only where the
   current file still proves it (header or the engine's own reading, class and fit of the values, no clear contradiction by the
   engine); a contradiction is asked about, never reused. The current document always wins. Reuse is applied *before* the required-field
   check so a source the engine cannot read alone becomes readable once a person has said what its columns are.

4. **Deterministic, explainable matching** - no ML, no embedding, no LLM. Drift is classified NONE / COSMETIC / ADDITIVE / MISSING /
   SEMANTIC_CONFLICT / MAJOR_CHANGE and the structure EXACT / COMPATIBLE / DIFFERENT, with the evidence behind the verdict.

5. **A correction is a new revision**; the old confirmation stays in a short history. A profile that existed before this decision is
   not trusted until a person confirms it again.

6. **Scope is the source's**: property + kind of data (the existing `DataSource` and its composite foreign keys). Cross-property and
   cross-domain learning is zero by construction, and tested.

## Consequences

* A source a person taught once is read with nothing to ask the next month (measured: the Source Learning Benchmark V1), and one that
  changed is asked only about what changed.
* The first confirmation after this decision is needed again for sources saved earlier: the price of not trusting what nobody can
  vouch for.
* Only one current structure per source is reused; keeping several structures per source would extend the same JSON (a list of
  revisions with their documents), not the schema. **Done by ADR 0034**: a source holds N recurring families.
* The reuse is invisible in the interface for now (`FileInspection.learning` is internal). A "Sorgente riconosciuta" notice, and a
  history view, can be built on it later without touching the engine.
