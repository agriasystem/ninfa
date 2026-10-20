// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DatiPeriodControl, DatiTabs, datiPanelId, datiTabId } from "./dati-tabs";

function tabs() {
  return screen.getAllByRole("tab");
}

describe("DatiTabs - WAI-ARIA tabs with manual activation", () => {
  it("is a labelled tablist of five tabs, exactly one selected", () => {
    render(<DatiTabs active="costs" onSelect={vi.fn()} />);

    const list = screen.getByRole("tablist", { name: "Sezioni di Dati" });
    expect(within(list).getAllByRole("tab")).toHaveLength(5);
    expect(tabs().map((tab) => tab.getAttribute("aria-selected"))).toEqual(["false", "false", "false", "true", "false"]);
  });

  it("wires each tab to its panel by id", () => {
    render(<DatiTabs active="overview" onSelect={vi.fn()} />);

    for (const tab of tabs()) {
      const key = tab.id.replace("dati-tab-", "") as Parameters<typeof datiPanelId>[0];
      expect(tab.id).toBe(datiTabId(key));
      expect(tab.getAttribute("aria-controls")).toBe(datiPanelId(key));
    }
  });

  it("puts ONLY the selected tab in the tab order (roving tabindex)", () => {
    render(<DatiTabs active="bookings" onSelect={vi.fn()} />);

    expect(tabs().map((tab) => tab.tabIndex)).toEqual([-1, 0, -1, -1, -1]);
  });

  it("moves focus with the arrow keys, Home and End - wrapping around - without selecting", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<DatiTabs active="overview" onSelect={onSelect} />);
    tabs()[0]?.focus();

    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(tabs()[1]);
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(document.activeElement).toBe(tabs()[3]);
    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(tabs()[2]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(tabs()[4]);
    await user.keyboard("{ArrowRight}"); // wraps to the first
    expect(document.activeElement).toBe(tabs()[0]);
    await user.keyboard("{ArrowLeft}"); // and back to the last
    expect(document.activeElement).toBe(tabs()[4]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(tabs()[0]);

    expect(onSelect).not.toHaveBeenCalled(); // browsing never navigates
  });

  it("selects the focused tab with Enter or Space", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<DatiTabs active="overview" onSelect={onSelect} />);
    tabs()[0]?.focus();

    await user.keyboard("{ArrowRight}{ArrowRight}{Enter}");
    expect(onSelect).toHaveBeenLastCalledWith("distribution");
    await user.keyboard("{ArrowRight}{ }");
    expect(onSelect).toHaveBeenLastCalledWith("costs");
  });

  it("selects a tab on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<DatiTabs active="overview" onSelect={onSelect} />);

    await user.click(screen.getByRole("tab", { name: "Personale" }));

    expect(onSelect).toHaveBeenCalledWith("labor");
  });

  it("sits in a horizontally scrolling container so the tabs stay reachable on a phone", () => {
    const { container } = render(<DatiTabs active="overview" onSelect={vi.fn()} />);

    expect(container.querySelector(".dati-tabs-scroller .dati-tabs")).not.toBeNull();
  });
});

describe("DatiPeriodControl", () => {
  it("offers 7 and 30 days and exposes the choice as pressed state, not colour alone", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<DatiPeriodControl period={30} onSelect={onSelect} />);

    const group = screen.getByRole("group", { name: "Periodo" });
    expect(within(group).getByRole("button", { name: "30 giorni" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(group).getByRole("button", { name: "7 giorni" }).getAttribute("aria-pressed")).toBe("false");

    await user.click(within(group).getByRole("button", { name: "7 giorni" }));
    expect(onSelect).toHaveBeenCalledWith(7);
  });
});
