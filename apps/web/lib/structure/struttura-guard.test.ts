import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { copy } from "@/lib/copy";

/**
 * Architectural guards for Struttura UI V1, enforced on the SOURCE rather than by convention: the page is
 * deterministic (no Mia, no model, no API), keeps its demo data in ONE file, speaks about the structure and
 * never in a PMS's vocabulary, adds no dependency, and keeps the responsive-critical CSS rules that cannot
 * be exercised in jsdom.
 */

const WEB = path.resolve(__dirname, "..", "..");

function read(relative: string): string {
  return readFileSync(path.join(WEB, relative), "utf8");
}

const DEMO_FILE = "lib/structure/demo-structure.ts";

function strutturaSources(): { file: string; text: string }[] {
  const files = [
    ...readdirSync(path.join(WEB, "components"))
      .filter((name) => /^struttura-.*\.tsx$/u.test(name) && !name.includes(".test."))
      .map((name) => `components/${name}`),
    ...readdirSync(path.join(WEB, "lib", "structure"))
      .filter((name) => name.endsWith(".ts") && !name.includes(".test."))
      .map((name) => `lib/structure/${name}`),
    "app/struttura/page.tsx",
  ];
  return files.map((file) => ({ file, text: read(file) }));
}

describe("Struttura sources", () => {
  const sources = strutturaSources();

  it("finds the Struttura sources", () => {
    expect(sources.length).toBeGreaterThanOrEqual(12);
    expect(sources.map((source) => source.file)).toContain(DEMO_FILE);
  });

  it("imports no Mia, Ask or model code, and reaches the backend ONLY through the data-source API", () => {
    for (const { file, text } of sources) {
      const imports = text.split("\n").filter((line) => /^\s*(import|export)\b.*\bfrom\b/u.test(line));
      for (const line of imports) {
        expect(line, `${file}: ${line}`).not.toMatch(/ask-ninfa|\/mia|anthropic|openai|gateway|language-model/iu);
        // the one API of this page is Fonti dati's own: no other client (decisions, data overview, auth...)
        const api = /from "@\/lib\/api\/([^"]+)"/u.exec(line)?.[1];
        if (api !== undefined) expect(api, `${file}: ${line}`).toBe("data-sources");
      }
      expect(text, file).not.toMatch(/\bfetch\(|askMiaHome|askNinfa|postMiaMessage|Chiedi a Mia/u);
    }
  });

  it("keeps every demo value in ONE file: no component or helper hardcodes a name, a system or a room type", () => {
    const demoValues = [
      /Villa Seren/u,
      /Bellagio/u,
      /\bMews\b/u,
      /SiteMinder/u,
      /Booking\.com/u,
      /TeamSystem/u,
      /\bClassic\b/u,
      /\bDeluxe\b/u,
      /Junior Suite/u,
      /\bCLS\b|\bDLX\b|\bJSU\b|\bSTE\b/u,
    ];
    for (const { file, text } of sources.filter((source) => source.file !== DEMO_FILE)) {
      for (const pattern of demoValues) expect(text, `${file} matches ${pattern}`).not.toMatch(pattern);
    }
    // ...and that one file says it is demo data
    expect(read(DEMO_FILE)).toMatch(/DEMO DATA/u);
  });

  it("never lets the real route show demo data: no source file imports the demo dataset", () => {
    // the real data source reports everything it has no real data for as not configured...
    const overview = read("lib/structure/overview.ts");
    expect(overview).toMatch(/rooms: \[\]/u);
    expect(overview).toMatch(/parameters: \{ opening: null, peakSeason: null, maxGuests: null \}/u);
    // ...the route passes no other source of data...
    expect(read("app/struttura/page.tsx")).not.toMatch(/getOverview|demoStructureOverview|demo-structure/u);
    // ...and nothing but the demo file itself even mentions the dataset in an import (a comment may name it)
    for (const { file, text } of sources.filter((source) => source.file !== DEMO_FILE)) {
      const imports = text.split("\n").filter((line) => /^\s*(import|export)\b.*\bfrom\b/u.test(line));
      for (const line of imports) {
        expect(line, `${file}: ${line}`).not.toMatch(/demo-structure|demoStructureOverview|DEMO_STRUCTURE/u);
      }
    }
  });

  it("keeps the data sources out of the structure model: they come from their own backend API", () => {
    const types = read("lib/structure/types.ts");
    expect(types).not.toMatch(/DataSource|provider|CONNECTED/u);
    expect(read("lib/structure/overview.ts")).not.toMatch(/\bsources\s*:/u);
  });

  it("lets every profile fact and every parameter be 'not configured' (null), but never the name or the timezone", () => {
    const types = read("lib/structure/types.ts");
    for (const field of [/type: string \| null;/u, /location: string \| null;/u, /roomCount: number \| null;/u, /currency: string \| null;/u, /mainSeason: MonthRange \| null;/u, /peakSeason: MonthRange \| null;/u, /maxGuests: number \| null;/u]) {
      expect(types).toMatch(field);
    }
    expect(types).toMatch(/\n  name: string;/u);
    expect(types).toMatch(/\n  timeZone: string;/u);
  });

  it("takes the property's name and timezone from the session", () => {
    expect(read("lib/structure/overview.ts")).toMatch(/name: property\.name,/u);
    expect(read("lib/structure/overview.ts")).toMatch(/timeZone: property\.timezone,/u);
  });

  it("speaks about the structure, never in a PMS's vocabulary or about data quality", () => {
    const literals = Array.from(read("lib/structure/copy.ts").matchAll(/"([^"\n]*)"|`([^`\n]*)`/gu)).map(
      (match) => match[1] ?? match[2] ?? "",
    );
    expect(literals.length).toBeGreaterThan(40);
    for (const literal of literals) {
      expect(literal).not.toMatch(
        /prenotazion|tariff|prezz|disponibilit|assegnaz|housekeeping|calendario|copertura|qualit|complet/iu,
      );
    }
  });

  it("derives no figure in the browser: no sum or arithmetic on the structure's numbers", () => {
    for (const { file, text } of sources.filter((source) => source.file.startsWith("components/"))) {
      expect(text, file).not.toMatch(/\.reduce\(/u);
      expect(text, file).not.toMatch(/(?:rooms|guests|adults|children|capacity)\w*\s*[-+*/]\s*\w*(?:rooms|guests|adults|children|capacity)/iu);
    }
  });
});

describe("navigation", () => {
  it("names the first section Oggi - the word Home is never a navigation label", () => {
    expect(copy.nav.today).toBe("Oggi");
    expect(Object.values(copy.nav)).not.toContain("Home");
    expect(Object.values(copy.nav)).toContain("Struttura");
  });

  it("keeps Mia out of the navigation: it is not a section", () => {
    expect(Object.keys(copy.nav).join(" ")).not.toMatch(/mia/iu);
    expect(Object.values(copy.nav)).not.toContain("Mia");
  });
});

describe("dependencies", () => {
  it("adds no dependency for Struttura", () => {
    const manifest = JSON.parse(read("package.json")) as { dependencies: Record<string, string> };
    expect(Object.keys(manifest.dependencies).sort()).toEqual(["@ninfa/contracts", "next", "react", "react-dom"]);
  });
});

describe("responsive-critical CSS (jsdom cannot lay out, so the rules are pinned in the stylesheet)", () => {
  const css = read("app/globals.css");
  const struttura = css.slice(css.indexOf("Struttura UI V1: the structure's profile"));

  it("finds the Struttura block", () => {
    expect(css.indexOf("Struttura UI V1: the structure's profile")).toBeGreaterThan(0);
  });

  it("uses the app's own font through inheritance: Struttura declares no font family of its own", () => {
    const families = Array.from(struttura.matchAll(/font-family:\s*([^;]+);/gu)).map((match) => match[1]);
    for (const family of families) expect(family).toBe("inherit");
  });

  it("wraps the parameter tiles instead of squeezing them", () => {
    expect(struttura).toMatch(/\.struttura-tiles \{[^}]*repeat\(auto-fit, minmax\(\d+px, 1fr\)\)/u);
  });

  it("lays the five source cards 5 across, then 3 + 2 below 1440px, 2 columns on a tablet, 1 on a phone", () => {
    // the loading skeleton shares the cards' grid at every width, so nothing jumps when the cards arrive
    const grid = String.raw`\.struttura-sources,\s*\.struttura-sources-skeleton \{\s*grid-template-columns:`;
    expect(struttura).toMatch(/\.struttura-sources \{[^}]*repeat\(5, minmax\(0, 1fr\)\)/u);
    expect(struttura).toMatch(
      new RegExp(String.raw`@media \(max-width: 1439px\) \{\s*${grid} repeat\(3, minmax\(0, 1fr\)\)`, "u"),
    );
    expect(struttura).toMatch(
      new RegExp(String.raw`@media \(max-width: 767px\) \{\s*${grid} repeat\(2, minmax\(0, 1fr\)\)`, "u"),
    );
  });

  it("keeps the room table's hidden header inside its scroller, so it cannot widen the page", () => {
    expect(struttura).toMatch(/\.struttura-table-scroll \{[^}]*position: relative;/u);
  });

  it("scrolls the room table inside its card instead of widening the page", () => {
    expect(struttura).toMatch(/\.struttura-table-scroll \{[^}]*overflow-x: auto;/u);
    expect(struttura).toMatch(/\.struttura-table \{[^}]*min-width: \d+px;/u);
    expect(struttura).toMatch(/\.struttura-screen \{[^}]*min-width: 0;/u);
    expect(struttura).toMatch(/\.struttura-card \{[^}]*min-width: 0;/u);
  });

  it("stacks the profile's second fact column under the photo below 1200px, and everything on a phone", () => {
    expect(struttura).toMatch(
      /@media \(max-width: 1199px\) \{\s*\.struttura-profile \{\s*grid-template-columns: 213px minmax\(0, 1fr\);[\s\S]*?\.struttura-facts--secondary \{\s*grid-column: 1 \/ -1;/u,
    );
    expect(struttura).toMatch(
      /@media \(max-width: 767px\) \{[\s\S]*?\.struttura-profile \{\s*grid-template-columns: minmax\(0, 1fr\);/u,
    );
    expect(struttura).toMatch(
      /@media \(max-width: 479px\) \{[\s\S]*?\.struttura-sources,\s*\.struttura-sources-skeleton \{\s*grid-template-columns: minmax\(0, 1fr\);/u,
    );
  });

  it("is light only and never uses the orange reserved for an actual decision", () => {
    expect(struttura).not.toMatch(/prefers-color-scheme/u);
    expect(struttura).not.toMatch(/--home-attention/u);
  });

  it("keeps a visible focus ring on the buttons, the menu triggers and the scrolling table", () => {
    expect(struttura).toMatch(
      /\.struttura-button:focus-visible,\s*\.struttura-more:focus-visible,\s*\.struttura-table-scroll:focus-visible \{\s*outline: 2px solid var\(--home-focus\)/u,
    );
  });
});
