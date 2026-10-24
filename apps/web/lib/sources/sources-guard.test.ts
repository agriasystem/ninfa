import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { sourcesCopy } from "./copy";

/**
 * Architectural guards for "Fonti dati" (Struttura), enforced on the SOURCE: the page tells the truth (no
 * vendor, no made-up state, no invented threshold), speaks plainly (no technical word), computes no business
 * figure in the browser, reaches the backend ONLY through its own API, and adds no dependency.
 */

const WEB = path.resolve(__dirname, "..", "..");

function read(relative: string): string {
  return readFileSync(path.join(WEB, relative), "utf8");
}

function sourceFiles(): { file: string; text: string }[] {
  const files = [
    ...readdirSync(path.join(WEB, "lib", "sources"))
      .filter((name) => name.endsWith(".ts") && !name.includes(".test."))
      .map((name) => `lib/sources/${name}`),
    ...readdirSync(path.join(WEB, "components"))
      .filter(
        (name) =>
          /^struttura-(sources|source-.*|import-.*|manage-dialog|modal)\.tsx$/u.test(name) &&
          !name.includes(".test."),
      )
      .map((name) => `components/${name}`),
    "lib/api/data-sources.ts",
  ];
  return files.map((file) => ({ file, text: read(file) }));
}

/** The code of a file without its comments (a comment may name the very words the copy must not use). */
function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//gu, "").replace(/^\s*\/\/.*$/gmu, "");
}

const SAMPLE_ARGUMENTS: unknown[][] = [["x", 2, 1, "y"], [["x", "y"]]];

/** Every string of a copy object, wherever it is nested (functions are called with sample arguments). */
function allStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") {
    for (const args of SAMPLE_ARGUMENTS) {
      try {
        return allStrings((value as (...args: unknown[]) => unknown)(...args));
      } catch {
        // this function takes another kind of argument: try the next sample
      }
    }
    throw new Error("a copy function could not be sampled");
  }
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value !== null && typeof value === "object") return Object.values(value).flatMap(allStrings);
  return [];
}

describe("Fonti dati sources", () => {
  const files = sourceFiles();

  it("finds the sources", () => {
    expect(files.length).toBeGreaterThanOrEqual(16);
  });

  it("never names a vendor or a product: what does not exist is only 'Prossimamente'", () => {
    const vendors = /\b(Mews|SiteMinder|Cloudbeds|TeamSystem|Opera|Passepartout|Zucchetti|Fidelio|Protel)\b/u;
    for (const { file, text } of files) expect(withoutComments(text), file).not.toMatch(vendors);
  });

  it("never offers a connection that does not exist: no OAuth, no credentials, no connector, no simulation", () => {
    for (const { file, text } of files) {
      expect(withoutComments(text), file).not.toMatch(/\boauth\b|credential(?!s: "include")|connector|simulat|apiKey|api_key|webhook/iu);
    }
  });

  it("speaks plainly: no technical word anywhere in the copy the hotelier reads", () => {
    const technical =
      /API key|webhook|endpoint|\bJSON\b|token|database|payload|schema|OAuth|credential|connector|adapter|provider|\b4\d\d\b|\b5\d\d\b|validation error|exception|stack/iu;
    const strings = allStrings(sourcesCopy);
    expect(strings.length).toBeGreaterThan(100);
    for (const text of strings) expect(text).not.toMatch(technical);
  });

  it("speaks the hotelier's words when matching columns: none of the words the brief rules out", () => {
    const ruledOut = /\bmapping\b|\bparser\b|canonical|normalized|data contract|\bdatacontract\b/iu;
    for (const text of allStrings(sourcesCopy)) expect(text).not.toMatch(ruledOut);
    // and the words the brief asks for are the ones on the screen
    const match = allStrings(sourcesCopy.match).join(" | ");
    for (const word of ["Abbina le colonne", "Ignora questa colonna", "Riconosciuto", "Da verificare", "Continua"]) {
      expect(match).toContain(word);
    }
    expect(allStrings(sourcesCopy.preview).join(" | ")).toContain("Salva questa configurazione");
    expect(allStrings(sourcesCopy.recognized).join(" | ")).toContain("Importa con questa configurazione");
  });

  it("uses the product's own words for the actions", () => {
    const labels = Object.values(sourcesCopy.actions).flatMap(allStrings).join(" | ");
    for (const word of ["Collega", "Carica", "Gestisci", "Rimuovi fonte", "Visualizza canali", "Configura fonte"]) {
      expect(labels).toContain(word);
    }
    expect(sourcesCopy.dialog.comingSoon).toBe("Prossimamente");
  });

  it("invents no threshold: no age limit, no 'old data' judgement, no arithmetic on a date or a count", () => {
    for (const { file, text } of files.filter((entry) => entry.file.startsWith("lib/sources/") || entry.file.startsWith("components/"))) {
      const code = withoutComments(text);
      expect(code, file).not.toMatch(/\bdaysAgo\b|\bSTALE\b|isStale|staleAfter|maxAge|threshold/u);
      expect(code, file).not.toMatch(/\.reduce\(/u);
      expect(code, file).not.toMatch(/(?:rows_total|created|updated|unchanged|rows_invalid)\s*[-+*/]\s*\w/u);
    }
    expect(allStrings(sourcesCopy.update).join(" ")).not.toMatch(/giorni fa|potrebbero non essere|non aggiornat/iu);
  });

  it("states and capabilities come from the backend: the page decides nothing about what exists", () => {
    const viewModel = read("lib/sources/view-model.ts");
    // a card is built FROM the backend card; nothing in the view model hardcodes a state per category
    expect(viewModel).toMatch(/switch \(state\)/u);
    expect(viewModel).not.toMatch(/state: "(CONNECTED|DERIVED)"/u);
    // the one thing the page may do with a state is DOWNGRADE a file source that never delivered
    expect(viewModel).toMatch(/return neverDelivered\(card\) \? "NOT_CONFIGURED" : card\.state;/u);
    const dialogs = read("components/struttura-source-dialogs.tsx");
    expect(dialogs).toMatch(/sources\.capabilities\.some/u);
    expect(dialogs).toMatch(/sources\.automatic_integrations\.length === 0/u);
  });

  it("never creates a source: the page has no call for it, and the dialogs call no API at all", () => {
    for (const { file, text } of files) {
      const code = withoutComments(text);
      expect(code, file).not.toMatch(/createDataSource|createSource|ensureSource|SOURCE_ALREADY_CONFIGURED/u);
      // only the removal (DELETE of a source the card already showed) is addressed by a source id
      if (file !== "lib/api/data-sources.ts") expect(code, file).not.toMatch(/\bdataSourceId\b/u);
    }
    // the only mutations are the imports (looking at a file, checking and trying a matching are POSTs that
    // write nothing - the backend says so and its tests pin it), the removal and forgetting a configuration
    const client = withoutComments(read("lib/api/data-sources.ts"));
    expect([...client.matchAll(/method: "(POST|DELETE|PUT|PATCH)"/gu)].map((match) => match[1]).sort()).toEqual([
      "DELETE",
      "DELETE",
      "POST",
      "POST",
      "POST",
      "POST",
      "POST",
      "POST",
      "POST",
    ]);
    // opening a dialog and choosing "Importa file" only changes what is shown
    const dialogs = withoutComments(read("components/struttura-source-dialogs.tsx"));
    expect(dialogs).not.toMatch(/@\/lib\/api\//u);
  });

  it("reaches the backend only through the data-source API client, and calls no model", () => {
    for (const { file, text } of files) {
      if (file === "lib/api/data-sources.ts") continue;
      const imports = text.split("\n").filter((line) => /^\s*(import|export)\b.*\bfrom\b/u.test(line));
      for (const line of imports) {
        expect(line, `${file}: ${line}`).not.toMatch(/ask-ninfa|\/mia|anthropic|openai|gateway|language-model/iu);
        const api = /from "@\/lib\/api\/([^"]+)"/u.exec(line)?.[1];
        if (api !== undefined) expect(["data-sources", "client"], `${file}: ${line}`).toContain(api);
      }
      expect(text, file).not.toMatch(/\bfetch\(/u);
    }
  });

  it("keeps demo data out of the production path: the fixtures live in tests only", () => {
    for (const { file, text } of files) {
      expect(file).not.toMatch(/fixture|demo|mock/iu);
      expect(text, file).not.toMatch(/test\/sources-support|demo-structure|demoStructureOverview/u);
    }
  });

  it("keeps the wire contract in @ninfa/contracts, in the backend's own words", () => {
    const contracts = readFileSync(path.join(WEB, "..", "..", "packages", "contracts", "src", "index.ts"), "utf8");
    for (const word of [
      "SourceCardKey",
      "SourceCardState",
      "DataSourceCard",
      "DataSourcesResponse",
      "ImportPreviewResponse",
      "ImportResultResponse",
      "ImportProblem",
    ]) {
      expect(contracts).toContain(word);
    }
    // the states the backend can produce, no more: an automatic connection is documented as never produced yet
    expect(contracts).toMatch(/"NOT_CONFIGURED"[\s\S]*"CONFIGURED_FILE"[\s\S]*"CONNECTED"[\s\S]*"DERIVED"/u);
  });
});

describe("Smart Import: the page decides nothing about the data", () => {
  const FIELD_KEYS =
    /"(source_record_id|booked_at|check_in|check_out|rooms|room_revenue|work_date|labor_category|planned_hours|actual_hours|planned_cost|actual_cost)"/u;
  const logic = [
    "lib/sources/use-import-flow.ts",
    "lib/sources/mapping-decision.ts",
    "lib/sources/sample-format.ts",
    "lib/sources/problem-text.ts",
    "components/struttura-import-mapping.tsx",
    "components/struttura-import-preview.tsx",
    "components/struttura-import-question.tsx",
    "components/struttura-import-understood.tsx",
    "lib/sources/understanding-format.ts",
    "components/struttura-import-dialog.tsx",
    "components/struttura-manage-dialog.tsx",
  ];

  it("names no field of any kind of data in its logic: what is required, and what a field is, come from the backend", () => {
    for (const file of logic) expect(withoutComments(read(file)), file).not.toMatch(FIELD_KEYS);
  });

  it("never decides on its own that a matching is enough: the button waits for the backend's answer", () => {
    const mapping = withoutComments(read("components/struttura-import-mapping.tsx"));
    expect(mapping).toMatch(/check\?\.valid === true/u);
    const flow = withoutComments(read("lib/sources/use-import-flow.ts"));
    expect(flow).toMatch(/state\.check\?\.valid !== true/u);
    expect(flow).not.toMatch(/requirement_groups|(?<!SHEET_)REQUIRED|\brequired\b/u);
  });

  it("offers the import only when the backend says every row can be imported", () => {
    const preview = withoutComments(read("components/struttura-import-preview.tsx"));
    expect(preview).toMatch(/validation\.can_import/u);
    expect(withoutComments(read("lib/sources/use-import-flow.ts"))).toMatch(/!state\.validation\.can_import/u);
  });

  it("sends the file only to the data-source API and reads it back in no other way", () => {
    const client = withoutComments(read("lib/api/data-sources.ts"));
    expect(client).toMatch(/readAsDataURL/u); // a file travels as text inside the request, never to a third party
    for (const file of logic) expect(read(file), file).not.toMatch(/\bfetch\(|XMLHttpRequest|sendBeacon/u);
  });
});

describe("dependencies", () => {
  it("adds no dependency for Fonti dati", () => {
    const manifest = JSON.parse(read("package.json")) as { dependencies: Record<string, string> };
    expect(Object.keys(manifest.dependencies).sort()).toEqual(["@ninfa/contracts", "next", "react", "react-dom"]);
  });
});

describe("responsive-critical CSS of the dialogs and the cards", () => {
  const css = read("app/globals.css");
  const block = css.slice(css.indexOf("Struttura UI V1: the structure's profile"));

  it("keeps a dialog inside the viewport and scrollable, on a phone too", () => {
    expect(block).toMatch(/\.struttura-modal \{[^}]*position: fixed;[^}]*inset: 0;/u);
    expect(block).toMatch(/\.struttura-modal__panel \{[^}]*width: min\(100%, \d+px\);[^}]*max-height: calc\(100dvh - 32px\);[^}]*overflow-y: auto;/u);
    expect(block).toMatch(/\.struttura-modal \{[^}]*overflow-y: auto;/u);
  });

  it("gives the dialogs the page's design tokens: a portal renders OUTSIDE the page's own scope", () => {
    // the variables the dialog's cards, borders and tiles use must be declared on the dialog too
    expect(block).toMatch(/\.struttura-screen,\s*\.struttura-modal \{\s*--struttura-gap:/u);
    const used = new Set(Array.from(block.matchAll(/var\((--struttura-[a-z-]+)\)/gu), (match) => match[1]));
    const declared = new Set(Array.from(block.matchAll(/^\s*(--struttura-[a-z-]+):/gmu), (match) => match[1]));
    for (const token of used) expect(declared, token).toContain(token);
  });

  it("lets the options of a dialog wrap instead of overflowing", () => {
    expect(block).toMatch(/\.struttura-option \{[^}]*flex-wrap: wrap;/u);
    expect(block).toMatch(/\.struttura-flow__actions \{[^}]*flex-wrap: wrap;/u);
    expect(block).toMatch(/\.struttura-flow__sample \{[^}]*overflow-x: auto;/u);
  });

  it("keeps a visible focus ring on every new control", () => {
    expect(block).toMatch(
      /\.struttura-source__link:focus-visible,\s*\.struttura-menu__item:focus-visible,\s*\.struttura-kind:focus-visible,\s*\.struttura-modal__close:focus-visible \{\s*outline: 2px solid var\(--home-focus\)/u,
    );
    expect(block).toMatch(/\.struttura-flow__pick:focus-within \{\s*outline: 2px solid var\(--home-focus\)/u);
  });

  it("respects reduced motion for the loading states", () => {
    expect(block).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*\.struttura-sources-skeleton__card,\s*\.struttura-flow__spinner \{\s*animation: none;/u,
    );
  });

  it("stays light and orange-free", () => {
    expect(block).not.toMatch(/prefers-color-scheme|--home-attention/u);
  });
});
