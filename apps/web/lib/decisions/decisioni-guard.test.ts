import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Architectural guards for the redesigned `/decisioni`, enforced on the SOURCE rather than by convention: the
 * page is deterministic (no Mia, no model), states only what the feed holds (no demo value from the reference,
 * no summed money, no Alta / Media / Bassa), adds no dependency, and keeps the responsive-critical CSS rules
 * that jsdom cannot lay out.
 */

const WEB = path.resolve(__dirname, "..", "..");

function read(relative: string): string {
  return readFileSync(path.join(WEB, relative), "utf8");
}

const FILES = [
  "components/decisioni-screen.tsx",
  "components/decisioni-hero.tsx",
  "components/decisioni-board.tsx",
  "components/decision-row.tsx",
  "lib/decisions/list-copy.ts",
  "lib/decisions/list-view-model.ts",
];

const sources = FILES.map((file) => ({ file, text: read(file) }));

describe("Decisioni sources", () => {
  it("imports no Mia, Ask or model code: the page is deterministic", () => {
    for (const { file, text } of sources) {
      const imports = text.split("\n").filter((line) => /^\s*(import|export)\b.*\bfrom\b/u.test(line));
      for (const line of imports) {
        expect(line, `${file}: ${line}`).not.toMatch(/ask-ninfa|\/mia|anthropic|openai|gateway|language-model/iu);
      }
      expect(text, file).not.toMatch(/askMiaHome|askNinfa|postMiaMessage|Chiedi a Mia/u);
    }
  });

  it("hardcodes no demo value of the reference mockup and no brand of another product", () => {
    const forbidden = [/1\.240/u, /\b09:31\b/u, /Villa Aurora/u, /Masseria Ninfa/u, /\$\s?\d/u, /\bwallet\b/iu];
    for (const { file, text } of sources) {
      for (const pattern of forbidden) expect(text, `${file} matches ${pattern}`).not.toMatch(pattern);
    }
  });

  it("never buckets the priority: no Alta / Media / Bassa anywhere in what a user can read", () => {
    for (const { file, text } of sources) {
      const literals = Array.from(text.matchAll(/"([^"\n]*)"|`([^`\n]*)`/gu)).map((match) => match[1] ?? match[2] ?? "");
      for (const literal of literals) expect(literal, file).not.toMatch(/\b(Alta|Media|Bassa)\b/u);
    }
  });

  it("sums no money and derives no business figure: a recorded estimate is shown per decision, never added up", () => {
    for (const { file, text } of sources) {
      expect(text, file).not.toMatch(/\.reduce\(/u);
      expect(text, file).not.toMatch(/Impatto (stimato )?totale|totale stimato/iu);
    }
  });

  it("makes no recommendation: problem + evidence only", () => {
    const copy = read("lib/decisions/list-copy.ts");
    const literals = Array.from(copy.matchAll(/"([^"\n]*)"|`([^`\n]*)`/gu)).map((match) => match[1] ?? match[2] ?? "");
    for (const literal of literals) {
      expect(literal).not.toMatch(/\b(dovresti|consigliamo|suggeriamo|ti consigliamo|rivedi|riduci|aumenta|verifica)\b/iu);
    }
  });

  it("adds no dependency", () => {
    const manifest = JSON.parse(read("package.json")) as { dependencies: Record<string, string> };
    expect(Object.keys(manifest.dependencies).sort()).toEqual(["@ninfa/contracts", "next", "react", "react-dom"]);
  });
});

describe("responsive-critical CSS (jsdom cannot lay out, so the rules are pinned in the stylesheet)", () => {
  const css = read("app/globals.css");
  const board = css.slice(css.indexOf("/decisioni: the decisions board"));

  it("finds the Decisioni stylesheet section", () => {
    expect(board.length).toBeGreaterThan(1000);
  });

  it("lays a row out as four zones from 1400px and as two lines below", () => {
    expect(board).toMatch(/\.decision-row \{[^}]*grid-template-columns: minmax\(0, 1\.6fr\) minmax\(250px, 0\.9fr\) minmax\(190px, 0\.62fr\) auto;/u);
    expect(board).toMatch(/@media \(min-width: 1400px\) and \(max-width: 1599px\)/u);
    expect(board).toMatch(/@media \(max-width: 1399px\) \{\s*\.decision-row \{[^}]*grid-template-areas:\s*"main main main"\s*"metric impact action";/u);
  });

  it("stacks a row on a phone and scrolls the pills inside themselves instead of widening the page", () => {
    expect(board).toMatch(/@media \(max-width: 719px\) \{[\s\S]*?\.decision-row \{\s*grid-template-columns: minmax\(0, 1fr\);/u);
    expect(board).toMatch(/\.decisioni-filters__pills \{\s*flex-wrap: nowrap;[^}]*overflow-x: auto;/u);
  });

  it("lets every grid child shrink (no min-content blow-out) and stretches the link over the row", () => {
    expect(board).toMatch(/\.decision-row__main \{[^}]*min-width: 0;/u);
    expect(board).toMatch(/\.decision-row__metric,\s*\.decision-row__impact \{\s*display: flex;\s*min-width: 0;/u);
    expect(board).toMatch(/\.decision-row__cta::after \{\s*position: absolute;\s*inset: 0;/u);
  });

  it("respects reduced motion", () => {
    expect(board).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.decisioni-skeleton__row \{\s*animation: none;/u);
  });

  it("is light only: no dark scheme is introduced", () => {
    expect(board).not.toMatch(/prefers-color-scheme/u);
  });

  it("keeps a visible focus ring on the pills, the sort control and the row's link", () => {
    expect(board).toMatch(/\.decisioni-pill:focus-visible,[\s\S]*?outline: 2px solid var\(--home-focus\)/u);
  });

  it("gives each of the four areas its own colour, paired in the markup with its name and icon", () => {
    for (const area of ["DISTRIBUTION", "COSTS", "LABOR"]) {
      expect(board).toContain(`.decision-row[data-area="${area}"]`);
    }
  });
});
