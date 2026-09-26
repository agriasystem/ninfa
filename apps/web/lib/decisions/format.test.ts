import { describe, expect, it } from "vitest";

import { formatCount, formatDecimal, formatHours, formatMoney, formatPercent } from "./format";

describe("formatDecimal", () => {
  it("formats an exact Decimal string to one fraction digit by default", () => {
    expect(formatDecimal("12.3456")).toBe("12,3");
  });

  it("renders null as an em dash, never as 'null' or an empty string", () => {
    expect(formatDecimal(null)).toBe("—");
  });

  it("never mutates the source string it was given", () => {
    const source = "12.3456";
    formatDecimal(source);
    expect(source).toBe("12.3456");
  });
});

describe("formatPercent", () => {
  it("appends % WITHOUT multiplying by 100 - the backend's percent_of() already did that", () => {
    expect(formatPercent("62.50")).toBe("62,5%");
  });

  it("renders null as an em dash", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatCount", () => {
  it("formats a plain integer count with Italian grouping", () => {
    expect(formatCount(3)).toBe("3");
    expect(formatCount(1200)).toBe("1.200");
  });

  it("renders null as an em dash", () => {
    expect(formatCount(null)).toBe("—");
  });
});

describe("formatHours", () => {
  it("appends an 'h' suffix", () => {
    expect(formatHours("12.00")).toBe("12,0 h");
  });
});

describe("formatMoney", () => {
  it("formats an amount + currency as localised money", () => {
    const result = formatMoney("482.30", "EUR");
    expect(result).toContain("482,30");
    expect(result).toMatch(/€/);
  });

  it("renders a non-numeric amount as an em dash rather than throwing", () => {
    expect(formatMoney("not-a-number", "EUR")).toBe("—");
  });
});
