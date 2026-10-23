# NINFA — Struttura UI V1 (the structure's profile and configuration)

`/struttura?property=…` describes the property the way NINFA needs to know it to read the data correctly:
its profile, its room inventory, the few operating parameters the analysis uses, and which systems feed it.
It is **not** a PMS, a CMS or a hotel page. This revision is a **frontend-only** screen: **no backend change,
no endpoint, no migration, no new dependency, no model, no Mia**. The visual source of truth is the approved
mockup of the screen.

## Composition

Title "Struttura" + subtitle + the button "Modifica struttura", then four numbered cards in this order
(`components/struttura-screen.tsx`):

| Card | Component | What it shows |
| --- | --- | --- |
| 1. Profilo struttura | `struttura-profile.tsx` | photo (or a neutral tile), name, type, star category, location; room count, timezone, currency, main season - each "Non configurata" until something sets it |
| 2. Inventario camere | `struttura-rooms.tsx` | a light table: room type, code, rooms, maximum occupancy, status (green dot "Attiva"), a "…" menu per row; "Modifica inventario". With no room type: the empty state "L'inventario camere non è ancora configurato" + "Configura inventario" |
| 3. Parametri operativi | `struttura-parameters.tsx` | three tiles: opening period, seasonality, relevant operating capacity - each "Non configurato/a" until set; "Modifica parametri" |
| 4. Fonti dati | `struttura-sources.tsx` | five compact cards (PMS, Channel Manager, OTA, Contabilità, Personale): a connected one with "Collegato" + the system + "Ultimo aggiornamento N min fa", any other "Non configurata" + "Nessuna fonte collegata" + "Collega fonte"; "+ Collega una nuova fonte" |

Shared pieces (card frame, the three button variants, the "…" trigger, the `StrutturaActions` contract) live in
`struttura-parts.tsx`. The route is `app/struttura/page.tsx`; `strutturaRoute()` in `lib/routes.ts` builds it
with the same `?property=` convention as every other screen. The sidebar item **Struttura** is now a real
link (`ShellSection` gained `"struttura"`); **Impostazioni** is the only item still drawn disabled ("In arrivo").
The first item stays **Oggi**, never "Home"; Mia is not a navigation item.

## Data: one seam, and NO demo value on the real route

**Rule: demo data may exist in the code for development and tests, but the real route never shows it.**
NINFA has no Struttura endpoint yet. `lib/structure/types.ts` defines `StructureOverview` — facts in the form a
backend would send them (IANA zone, ISO currency, month numbers, an ISO timestamp), never display strings — in
which **"not configured" is a first-class state**: a profile fact or a parameter nothing has set is `null`, the room
list is empty, a source is `NOT_CONNECTED`.

`getStructureOverview(property)` (`lib/structure/overview.ts`) is what `/struttura?property=…` renders, and the
**single function to replace** with an API call. Today it knows exactly two real things, both from the session: the
property's **name** and **timezone** (so the page never contradicts the name in the header). Everything else is not
configured, and the page says so in the same neutral words everywhere:

| Where | Without real data |
| --- | --- |
| Tipologia, Categoria, Località, Valuta, Stagionalità principale | "Non configurata" (grey, regular weight) |
| Numero camere | "Non configurato" |
| Foto | a neutral tile, no image |
| Inventario camere | empty state "L'inventario camere non è ancora configurato" + **"Configura inventario"** (no table, no "Modifica inventario") |
| Periodo di apertura | "Non configurato" |
| Stagionalità, Capacità operativa rilevante | "Non configurata" |
| Fonti dati (all five) | "Non configurata", "Nessuna fonte collegata", "Collega fonte" |

The complete example dataset of the approved mockup — Villa Serenità, Hotel, 4 stelle, Bellagio (CO), 32 camere in
four room types, the three parameters, Mews / SiteMinder / Booking.com connected — is `demoStructureOverview(now)` in
`lib/structure/demo-structure.ts`, an **explicit fixture**: nothing imports it except tests and whoever wants to look
at the full page by passing `getOverview={(_property, now) => demoStructureOverview(now)}` to `StrutturaScreen`
(`getOverview` is the same seam as the API call; the route never passes it, and a guard pins that no source file
imports the demo). The demo's capacity is the room types' theoretical capacity (8×2 + 12×3 + 8×3 + 4×4 =
**92 ospiti**) and a test keeps them equal; it may be separated from the theoretical capacity only once an explicit
operating configuration exists. The provider's name exists only **inside a connected connection**
(`DataSourceConnection`): the type forbids one on a source that is not connected, for every category.

Wording lives in `lib/structure/copy.ts`; month ranges, the zone label ("Europe/Rome (CET)", the standard-time
abbreviation), the currency label ("Euro (€)"), "2 adulti + 1 bambino" and the age ("4 min fa") are built in
`lib/structure/format.ts`.

## Product rules the page keeps

- **Struttura vs Dati.** Struttura says *which systems are connected and when each last delivered*; it never says
  how good, how far back or how complete the data is - that is the Dati section's job. A guard pins this.
- **No PMS vocabulary.** No bookings, rates, availability, calendar, housekeeping or room assignment anywhere in
  the copy; the inventory only describes room types.
- **No parameter on a whim.** A parameter belongs in card 3 only once an NINFA engine actually uses it.
- **No vendor logos.** Each category has a neutral icon; connected and not-connected are told apart by pill text,
  icon tint and action, not by colour alone. Green appears only for "connected" and "active"; nothing is orange.
- **Buttons are drawn, not wired.** There is no write path for the structure, so every button is a real, focusable
  `<button>` whose handler is an **optional** prop of `StrutturaScreen` (`StrutturaActions`); without one a click
  does nothing. No modal, form or workflow is invented. The "…" triggers name what they act on
  ("Azioni per Suite", "Azioni per OTA") and open nothing yet.

## Layout and responsiveness

Same shell variant as Dati (`wide`). From 1440px the source cards sit five across, then 3 + 2 below it, 2 columns
on a tablet, 1 on a phone; the parameter tiles wrap (`auto-fit`); the profile's second column of facts drops under
the photo below 1200px and everything is single column on a phone. The room table scrolls **inside its card**
(a named, focusable region) and never widens the page; its visually-hidden "Azioni" header is kept inside that
scroller (`position: relative`) so it cannot push the page past the viewport. Light only; Poppins is inherited from
the app (the block declares no font family).

## Tests

`components/struttura-screen.test.tsx` (the real route with no data: every fact, the inventory, the parameters and
the sources are neutral and **no value of the demo dataset appears anywhere**; the explicit demo fixture renders the
complete page; buttons and handlers; no Mia / network), `lib/structure/overview.test.ts` (what the real overview knows,
that it carries no demo value, the demo's internal consistency - capacity 92 = the rooms, room count 32 = the
inventory - and the type that keeps a provider off a source that is not connected), `lib/structure/format.test.ts`
(formatters), the architectural guard `lib/structure/struttura-guard.test.ts` (no Mia/API import; demo values only in
`demo-structure.ts`; **no source file imports the demo and the route passes no `getOverview`**; every optional fact is
nullable; no PMS vocabulary; no dependency; "Oggi" not "Home"; the responsive-critical CSS rules) and the updated
`components/app-shell.test.tsx` (Struttura is a link with the current-page state; no item of the main navigation is
disabled).

## Deferred

The Struttura endpoint and the edit flows behind the buttons; real photos (a structure without one shows a neutral tile;
the placeholder image belongs to the demo fixture only); a per-source menu and the "Collega" flow; stored profile
facts (type, star category, location, currency, seasons), room types, operating parameters and connected systems
per property.
