import { describe, expect, it } from "vitest";

import { mergeAnswers } from "./mapping-decision";
import { hoursText, isoDateText, moneyText } from "./understanding-format";

describe("how what NINFA understood is written", () => {
  it("writes hours the way the hotel does", () => {
    expect(hoursText("410")).toBe("410");
    expect(hoursText("420.5")).toBe("420,5");
    expect(hoursText("1234.5")).toBe("1.234,5");
    expect(hoursText("not a number")).toBe("not a number");
  });

  it("writes money in euros, grouped, with two decimals", () => {
    expect(moneyText("6304.60", "EUR")).toBe("€6.304,60");
    expect(moneyText("12.5", null)).toBe("€12,50");
    expect(moneyText("12.5", "USD")).toBe("12,50 USD");
  });

  it("writes a calendar day in Italian, whatever the time zone of the browser", () => {
    expect(isoDateText("2026-10-26")).toBe("26 ottobre 2026");
    expect(isoDateText("2026-11-01")).toBe("1 novembre 2026");
  });
});

describe("what the person has said stays said", () => {
  it("keeps the columns and the words answered before and adds the new ones", () => {
    const first = mergeAnswers({}, { column_fields: { Ore: "x" }, labels: { role_mapping: { HK: "A" } } });
    const second = mergeAnswers(first, {
      column_fields: { Codice: "y" },
      labels: { role_mapping: { Turno: "B" }, category_mapping: { Boh: "C" } },
      period_start: "2026-10-28",
    });

    expect(second.column_fields).toEqual({ Ore: "x", Codice: "y" });
    expect(second.labels).toEqual({ role_mapping: { HK: "A", Turno: "B" }, category_mapping: { Boh: "C" } });
    expect(second.period_start).toBe("2026-10-28");
  });

  it("lets a newer answer replace an older one about the same thing", () => {
    expect(mergeAnswers({ department_value: "A" }, { department_value: "B" }).department_value).toBe("B");
  });
});
