import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Architectural guards for Dati UI V1, enforced on the SOURCE rather than by convention: the page is
 * deterministic (no Mia, no model), shows only what the backend sent (no demo value), adds no dependency,
 * and keeps the responsive-critical CSS rules that cannot be exercised in jsdom.
 */

const WEB = path.resolve(__dirname, "..", "..");

function read(relative: string): string {
  return readFileSync(path.join(WEB, relative), "utf8");
}

function datiSources(): { file: string; text: string }[] {
  const files = [
    ...readdirSync(path.join(WEB, "components")).filter((name) => /^dati-.*\.tsx$/u.test(name) && !name.includes(".test.")).map((name) => `components/${name}`),
    ...readdirSync(path.join(WEB, "lib", "data")).filter((name) => name.endsWith(".ts") && !name.includes(".test.")).map((name) => `lib/data/${name}`),
    "lib/api/data-overview.ts",
    "app/dati/page.tsx",
  ];
  return files.map((file) => ({ file, text: read(file) }));
}

describe("Dati sources", () => {
  const sources = datiSources();

  it("finds the Dati sources", () => {
    expect(sources.length).toBeGreaterThanOrEqual(18);
  });

  it("imports no Mia, Ask or model code: the page is deterministic", () => {
    for (const { file, text } of sources) {
      const imports = text.split("\n").filter((line) => /^\s*(import|export)\b.*\bfrom\b/u.test(line));
      for (const line of imports) {
        expect(line, `${file}: ${line}`).not.toMatch(/ask-ninfa|\/mia|anthropic|openai|gateway|language-model/iu);
      }
      expect(text, file).not.toMatch(/askMiaHome|askNinfa|postMiaMessage|Chiedi a Mia/u);
    }
  });

  it("hardcodes no demo value, no reference-brand word and no financial term", () => {
    const forbidden = [
      /Code XR/u,
      /Vertix/u,
      /\$\s?\d/u, // a dollar amount
      /631[.,]288/u,
      /\bwallet\b/iu,
      /\bTransfer\b/u,
      /Good morning/u,
      /Masseria Ninfa/u, // a property name comes from the session, never from the source
      /Villa Aurora/u,
      /\b62,8\b|\b72,2\b|\b27,8\b|\b343\b/u, // the figures of the brief's own examples
    ];
    for (const { file, text } of sources) {
      for (const pattern of forbidden) expect(text, `${file} matches ${pattern}`).not.toMatch(pattern);
    }
  });

  it("never uses accounting words for what NINFA does not have", () => {
    const user = sources.find((source) => source.file === "lib/data/copy.ts")?.text ?? "";
    // strip the doc comment that lists these words as FORBIDDEN, then check every string literal
    const literals = Array.from(user.matchAll(/"([^"\n]*)"|`([^`\n]*)`/gu)).map((match) => match[1] ?? match[2] ?? "");
    for (const literal of literals) {
      expect(literal).not.toMatch(/\b(fatturato|incassi|margine|utile|RevPAR|cancellazion|no-show|previsione|concorrenti|benchmark)\b/iu);
    }
  });

  it("derives no business figure in the browser: no arithmetic on an API value", () => {
    // geometry of a bar / a segment and the minus sign are presentation; a sum, difference or ratio of two
    // backend figures is business logic and belongs to the backend.
    const components = sources.filter((source) => source.file.startsWith("components/"));
    for (const { file, text } of components) {
      expect(text, file).not.toMatch(/\.reduce\(/u);
      expect(text, file).not.toMatch(/(?:rooms|revenue|adr|room_nights|share|occupancy|hours|cost)\w*\s*[-+*/]\s*\w*(?:rooms|revenue|adr|room_nights|share|occupancy|hours|cost)/u);
    }
  });
});

describe("dependencies", () => {
  it("adds no charting library or any other dependency for Dati", () => {
    const manifest = JSON.parse(read("package.json")) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };
    expect(Object.keys(manifest.dependencies).sort()).toEqual(["@ninfa/contracts", "next", "react", "react-dom"]);
    const all = Object.keys({ ...manifest.dependencies, ...manifest.devDependencies });
    for (const name of all) expect(name).not.toMatch(/chart|recharts|d3|victory|nivo|apex|echarts|plotly/iu);
  });
});

describe("responsive-critical CSS (jsdom cannot lay out, so the rules are pinned in the stylesheet)", () => {
  const css = read("app/globals.css");
  const dati = css.slice(css.indexOf("Dati UI V1: the operational data workspace"));

  it("composes three columns only from 1440px", () => {
    const block = /@media \(min-width: 1440px\) \{\s*\.dati-grid--overview \.dati-cell--occupancy,[\s\S]*?\.dati-cell--ota \{\s*grid-column: span 4;[\s\S]*?\.dati-cell--table \{\s*grid-column: span 8;/u;
    expect(dati).toMatch(block);
  });

  it("stacks the major cards on a tablet and a phone", () => {
    expect(dati).toMatch(/@media \(max-width: 1023px\) \{[\s\S]*?\.dati-cell--occupancy,[\s\S]*?\.dati-cell--kpis \{\s*grid-column: span 12;/u);
    expect(dati).toMatch(/@media \(max-width: 479px\) \{\s*\.dati-kpis \{\s*grid-template-columns: minmax\(0, 1fr\);/u);
  });

  it("scrolls the tabs and the tables inside themselves instead of widening the page", () => {
    expect(dati).toMatch(/\.dati-tabs-scroller \{[^}]*overflow-x: auto;/u);
    expect(dati).toMatch(/\.dati-table__scroll \{[^}]*overflow: auto;/u);
    expect(dati).toMatch(/\.dati-grid \{[^}]*minmax\(0, 1fr\)/u);
    expect(dati).toMatch(/\.dati-cell \{[^}]*min-width: 0;/u);
  });

  it("respects reduced motion", () => {
    expect(dati).toMatch(/@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.dati-skeleton__card \{\s*animation: none;/u);
  });

  it("is light only: no dark scheme is introduced", () => {
    expect(dati).not.toMatch(/prefers-color-scheme/u);
  });

  it("keeps a visible focus ring on the tabs, the period control and the table filter", () => {
    expect(dati).toMatch(/\.dati-tab:focus-visible,[\s\S]*?outline: 2px solid var\(--home-focus\)/u);
  });
});
