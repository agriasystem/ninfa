# NINFA — Importa file V1 (`/importa-file`: the person hands over the file, NINFA works out what it is)

Bringing a file into NINFA used to be a dialog opened from a card of Struttura > Fonti dati, which meant the person had to
say first what kind of data the file holds. It is now a section of its own in the main navigation.

| | |
|---|---|
| **Struttura** | configures the structure and says where its data come from |
| **Importa file** | brings new data in |

**No migration. No new dependency. No change to the engine.** The page consumes Smart Import 2.1 through the API it already
had; the one backend addition is a read for "Importazioni recenti".

## The flow

```
choose -> reading the document -> trying every row -> "File riconosciuto" + one button -> import -> "Importazione completata"
                               \-> ASK     one question from the backend at a time
                               \-> MANUAL  says so; the columns open only if the person asks ("Abbina le colonne")
                               \-> BLOCKED why it cannot be imported, and that nothing was
                               \-> no kind of data in the document: the person says which, or chooses another file
```

`lib/sources/use-import-flow.ts` walks the steps. The screens of a question, of the summary and of the columns are the ones
Smart Import already had (`struttura-import-*.tsx`); the page adds the drop zone (`importa-file-dropzone.tsx`), the steps
around them (`importa-file-flow.tsx`) and the list (`importa-file-recent.tsx`). The frontend parses nothing, maps nothing and
asks nothing of its own: a file leaves the browser as base64 inside the request, and everything said about it is the backend's.

The progress is the requests, not a guess: "reading" while `import-understanding` is out, "verifying" while `import-validation`
is out. A step reads as done only once its request has come back; there is no percentage and no timer.

Nothing is written before the person presses "Importa dati". The source is the backend's business as it always was: an import
reuses the source of that kind of data (`DataSourcesService._source_for_import`) and one comes to exist only if the import
succeeds.

## The kind of data: the engine's verdict, not a card

Every API of the family takes a `domain`, because a card used to supply it. The engine, though, already scores the three kinds
on every reading and states its verdict in `understanding.detection`, whichever kind it was asked to read the file as. So the
page reads the file once under a fixed first kind (`FIRST_READING`, which stands for no choice of the person's) and:

| Verdict | What the page does |
|---|---|
| points at a kind (HIGH or MEDIUM) | follows it: reads the file as that kind if it was not the first one, and the engine's answer about THAT kind decides what happens |
| points nowhere (LOW), with a table | asks the person which kind, from the kinds the backend scored; the answer travels as `confirmed_domain` |
| no table at all | shows the backend's blocker: there is nothing to choose |

MEDIUM is followed with no "Corretto?" on purpose. With a card, an agreeing MEDIUM asked nothing because the card was the
confirmation; here the confirmation is the summary, which names the kind right above the only button that imports. Asking would
add a question to files the engine reads correctly (see below) without protecting anything the button does not.

This was measured before it was built, because the benchmarks had only ever tried documents on a card. Both corpora (672
documents: the 240 of the official benchmark and the 432 of Benchmark V2), read with no card, engine at the state of `e8e6a1b`:

| | |
|---|---|
| HIGH verdicts on the 574 positive documents | 544, **all right** |
| MEDIUM verdicts | 15: 14 right; the wrong one (restaurant sales read as staff) ends MANUAL |
| LOW verdicts | 15: 9 are documents that are none of the three, 6 have their data on a hidden sheet or only a weekly summary |
| **Wrong kind AND READY** | **0** |
| READY on the card, not READY without it | **0** |
| READY without the card, not on the wrong one it was uploaded on | 2 (staff files under a booking title: the card was the mistake) |
| READY among the 98 negatives and unsupported files | 4, all real files of that kind: 2 staff files uploaded on the wrong card in the benchmark, and 2 files with totals that do not add up, where the summary says so in red |
| Exceptions | 0 |

Cost: a file that is not bookings is read twice, so it travels once more (up to 10 MB). Making `domain` optional in
`import-understanding` would avoid that and is the natural follow-up, but it changes the engine's entry point, which this gate
does not need to do.

## MANUAL and BLOCKED

MANUAL used to open the column table directly. It now says first that NINFA cannot go on alone, with what is missing in the
hotelier's words, and the table opens only on "Abbina le colonne": a capability kept, never a step of the way. A READY reading
that the dry run contradicts ends in the same place. The summary now also explains rows that cannot be imported, which it used
to leave to a missing button.

## Struttura

Fonti dati keeps everything it says: the five cards, their state, "Gestisci", the saved configuration, the removal, "Collega una
nuova fonte". What changed is how a file is reached:

| Was | Is |
|---|---|
| "Carica nuovo file", "Importa file" in "Collega fonte" and in the wizard: a dialog with a file input | a link to `/importa-file` (plus "Importa un file" in the header of the block) |
| "Modifica associazioni": the same dialog, from the columns | a link to `/importa-file?review=<kind>`: the same page, straight to the columns of that kind of source |
| "Scarica modello CSV": inside the dialog | next to the link in "Collega fonte" |

**The one file input left in Struttura is an electronic invoice (XML)**, in `struttura-invoice-dialog.tsx`. The page reads CSV and
Excel only, as this version was scoped, so that is the only way an invoice has in: removing it would have dropped a working
capability, and it duplicates nothing. A register of costs in CSV / Excel goes to the page like any other file. A guard test pins
that this is the only file input in Struttura and what it accepts.

## Importazioni recenti

`GET /api/v1/properties/{property_id}/data-sources/imports`, the latest 10 attempts of the property, newest first: the name of the
file, the kind of data, how it ended, when. Everything comes from `import_jobs`, `import_files` and `data_sources` as they are.

- Property-scoped through `resolve_property_scope` like every route of the family: the same 404 for a foreign property.
- The name of a file was chosen by a person and may name one: it passes `PersonalDataGuard`, so an e-mail address, a telephone
  number, a tax code or an IBAN never travels. A name that is just a person's name is not recognised as such, and is shown to
  members of the same workspace.
- A failed attempt says only that it failed. `error_code` and `error_message` are for operators and never travel.
- Not offered: how many rows an attempt imported. `import_jobs` does not record it, and saying it would need a migration.

The browser keeps no history of its own.

## After the import

The page takes a file to the data; the Decision Engine stays on the server. An import starts no analysis, today as before, and
the page starts none: the automatic analysis runs on its own schedule. "Importazione completata" therefore says "I nuovi dati
entreranno nella prossima analisi di NINFA" and offers "Vai a Oggi", without going there on its own.

## Errors

Refused in the browser, with nothing sent: a format that is not CSV or Excel, an empty file, a file over the 10 MB of the backend's
own limit (the backend still decides: this only spares the browser from reading it into memory), several files at once. Everything
else is the backend's answer in a plain sentence: a file it cannot read, an import that fails, another import running, several sources
of a kind (`SEVERAL_SOURCES`), a file the browser can no longer read. A session that has ended, or a property no longer the person's,
goes back through the session check and from there to the login. A file dropped beside the zone does not make the browser leave the page.

## Tests

`importa-file-screen.test.tsx` (the page, the drop zone, the verdict, every state, the list), `importa-file-understanding.test.tsx`
and `importa-file-matching.test.tsx` (the Smart Import screens, moved here from the dialog), `struttura-sources.test.tsx` (Fonti dati
leads to the page, the invoice dialog, "Gestisci"), `test_data_sources_recent_imports.py` (the read), and the guards in
`sources-guard.test.ts`: one way in, no reading of a file in the browser, no kind guessed by the page, no browser storage, no analysis.

## Decisions to confirm

1. **Invoices stay in Struttura.** The brief scopes the page to CSV / XLSX. Moving XML to the page later is a small change: the flow
   would route `.xml` to the existing preview, and the dialog would go away.
2. **MEDIUM is followed without a question** (see above).
3. **The `struttura-import-*` components and the `struttura-flow` CSS keep their names**, though the page now owns them: renaming
   them is mechanical and would have hidden the real changes of this diff.
