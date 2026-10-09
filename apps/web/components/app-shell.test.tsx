// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PropertyAccess } from "@ninfa/contracts";

import { AppShell, type AppShellProps } from "./app-shell";
import { useShellLogo } from "./shell-logo-context";

const useSessionMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));

function property(id: string, name: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name, slug: name.toLowerCase(), timezone };
}

function signedIn(overrides: { display_name?: string | null; logout?: () => Promise<void> } = {}) {
  useSessionMock.mockReturnValue({
    session: {
      user: {
        id: "u1",
        email: "luca@hotel.example",
        display_name: overrides.display_name === undefined ? "Luca Bianchi" : overrides.display_name,
      },
      session: { expires_at: "2026-12-31T00:00:00Z" },
      workspaces: [],
    },
    logout: overrides.logout ?? vi.fn().mockResolvedValue(undefined),
  });
}

function renderShell(props: Partial<AppShellProps> = {}) {
  return render(
    <AppShell
      properties={[property("p1", "Hotel Quercia")]}
      selectedPropertyId="p1"
      onSelectProperty={vi.fn()}
      onLoggedOut={vi.fn()}
      activeSection="oggi"
      {...props}
    >
      <div>page content</div>
    </AppShell>,
  );
}

beforeEach(() => {
  useSessionMock.mockReset();
  signedIn();
});

describe("AppShell - structure and landmarks", () => {
  it("renders the page content inside one main landmark, with a skip link to it", () => {
    renderShell();

    const main = screen.getByRole("main");
    expect(within(main).getByText("page content")).not.toBeNull();
    const skip = screen.getByRole("link", { name: "Vai al contenuto" });
    expect(skip.getAttribute("href")).toBe("#main-content");
    expect(main.getAttribute("id")).toBe("main-content");
  });

  it("has a labelled primary navigation with the four approved sections, in order", () => {
    renderShell();

    const nav = screen.getByRole("navigation", { name: "Navigazione principale" });
    const items = within(nav).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Oggi",
      "Decisioni",
      expect.stringContaining("Dati"),
      expect.stringContaining("Struttura"),
    ]);
  });

  it("no longer carries the old topbar (wordmark text, e-mail line, loose logout button)", () => {
    const { container } = renderShell();

    expect(container.querySelector(".app-shell__topbar")).toBeNull();
    expect(screen.queryByText("luca@hotel.example")).toBeNull(); // only inside the closed profile menu
    expect(screen.queryByRole("button", { name: "Esci" })).toBeNull();
  });
});

describe("AppShell - navigation", () => {
  it("makes Oggi and Decisioni real links that keep the property context", () => {
    renderShell();

    expect(screen.getByRole("link", { name: "Oggi" }).getAttribute("href")).toBe("/oggi?property=p1");
    expect(screen.getByRole("link", { name: "Decisioni" }).getAttribute("href")).toBe(
      "/decisioni?property=p1",
    );
  });

  it("links carry no property query when the account has no property", () => {
    renderShell({ properties: [], selectedPropertyId: "" });

    expect(screen.getByRole("link", { name: "Oggi" }).getAttribute("href")).toBe("/oggi");
    expect(screen.getByRole("link", { name: "Decisioni" }).getAttribute("href")).toBe("/decisioni");
  });

  it("marks Oggi as the current page when the Home is active", () => {
    renderShell({ activeSection: "oggi" });

    expect(screen.getByRole("link", { name: "Oggi" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Decisioni" }).getAttribute("aria-current")).toBeNull();
  });

  it("marks Decisioni as the current page for the decisions list AND the Decision Detail", () => {
    renderShell({ activeSection: "decisioni" });

    expect(screen.getByRole("link", { name: "Decisioni" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Oggi" }).getAttribute("aria-current")).toBeNull();
  });

  it("draws Dati and Struttura as disabled, link-less items with a discreet 'In arrivo'", () => {
    renderShell();

    for (const name of ["Dati", "Struttura"]) {
      const item = screen.getByText(name).closest("[aria-disabled='true']");
      expect(item, name).not.toBeNull();
      expect(item?.getAttribute("href")).toBeNull();
      expect(item?.tagName).not.toBe("A");
      expect(item?.getAttribute("tabindex")).toBeNull(); // never a dead tab stop
      expect(within(item as HTMLElement).getByText("In arrivo")).not.toBeNull();
    }
    expect(screen.queryByRole("link", { name: "Dati" })).toBeNull();
  });

  it("draws Impostazioni as disabled and link-less, with its own accessible name", () => {
    renderShell();

    const settings = screen.getByLabelText("Impostazioni (in arrivo)");
    expect(settings.getAttribute("aria-disabled")).toBe("true");
    expect(settings.getAttribute("href")).toBeNull();
    expect(settings.tagName).not.toBe("A");
  });

  it("never links to a page that does not exist", () => {
    const { container } = renderShell();

    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    for (const href of hrefs) {
      expect(href === "#main-content" || href?.startsWith("/oggi") || href?.startsWith("/decisioni")).toBe(
        true,
      );
    }
  });
});

describe("AppShell - profile menu", () => {
  it("is closed by default and discloses display name, e-mail and Esci on click", async () => {
    const user = userEvent.setup();
    renderShell();
    const toggle = screen.getByRole("button", { name: "Profilo e account" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await user.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByRole("group", { name: "Profilo e account" });
    expect(within(panel).getByText("Luca Bianchi")).not.toBeNull();
    expect(within(panel).getByText("luca@hotel.example")).not.toBeNull();
    expect(within(panel).getByRole("button", { name: "Esci" })).not.toBeNull();
  });

  it("omits the display name when the account has none (still shows the e-mail)", async () => {
    signedIn({ display_name: null });
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Profilo e account" }));

    const panel = screen.getByRole("group", { name: "Profilo e account" });
    expect(within(panel).getByText("luca@hotel.example")).not.toBeNull();
    expect(panel.querySelector(".profile-menu__name")).toBeNull();
  });

  it("closes on Escape and returns focus to the profile button", async () => {
    const user = userEvent.setup();
    renderShell();
    const toggle = screen.getByRole("button", { name: "Profilo e account" });
    await user.click(toggle);

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("group", { name: "Profilo e account" })).toBeNull();
    expect(document.activeElement).toBe(toggle);
  });

  it("closes on a click outside", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: "Profilo e account" }));

    await user.click(screen.getByText("page content"));

    expect(screen.queryByRole("group", { name: "Profilo e account" })).toBeNull();
  });

  it("is keyboard operable: the panel's Esci is the next tab stop after the button", async () => {
    const user = userEvent.setup();
    renderShell();
    const toggle = screen.getByRole("button", { name: "Profilo e account" });
    toggle.focus();
    await user.keyboard("{Enter}");

    await user.tab();

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Esci" }));
  });

  it("Esci calls session.logout() and then onLoggedOut", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    const onLoggedOut = vi.fn();
    signedIn({ logout });
    const user = userEvent.setup();
    renderShell({ onLoggedOut });

    await user.click(screen.getByRole("button", { name: "Profilo e account" }));
    await user.click(screen.getByRole("button", { name: "Esci" }));

    expect(logout).toHaveBeenCalledOnce();
    expect(onLoggedOut).toHaveBeenCalledOnce();
  });
});

describe("AppShell - property header", () => {
  it("shows the REAL property name as static text - no selector, no fake chevron - for one property", () => {
    const { container } = renderShell({
      properties: [property("p1", "Resort Aurora")],
      selectedPropertyId: "p1",
    });

    expect(screen.getByText("Resort Aurora").tagName).toBe("P");
    expect(screen.queryByLabelText("Struttura attiva")).toBeNull();
    expect(container.querySelector(".property-selector__chevron")).toBeNull();
  });

  it("shows today's date in the PROPERTY's own timezone, with the year", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    // 22:30 UTC on 7 October is already 8 October in Rome (UTC+2) but still 7 October in Honolulu.
    vi.setSystemTime(new Date("2026-10-07T22:30:00Z"));
    try {
      const { unmount } = renderShell({
        properties: [property("p1", "Hotel Roma", "Europe/Rome")],
        selectedPropertyId: "p1",
      });
      expect(screen.getByText("8 ottobre 2026")).not.toBeNull();
      unmount();

      renderShell({
        properties: [property("p2", "Resort Honolulu", "Pacific/Honolulu")],
        selectedPropertyId: "p2",
      });
      expect(screen.getByText("7 ottobre 2026")).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the existing property selector (native select) when there are several properties", async () => {
    const user = userEvent.setup();
    const onSelectProperty = vi.fn();
    renderShell({
      properties: [property("p1", "Hotel A"), property("p2", "Hotel B")],
      selectedPropertyId: "p1",
      onSelectProperty,
    });

    const select = screen.getByLabelText("Struttura attiva") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    await user.selectOptions(select, "p2");
    expect(onSelectProperty).toHaveBeenCalledWith("p2");
  });

  it("renders no header at all when the account has no property (0 properties)", () => {
    const { container } = renderShell({ properties: [], selectedPropertyId: "" });

    expect(container.querySelector(".property-header")).toBeNull();
    expect(screen.getByText("page content")).not.toBeNull();
  });
});

describe("AppShell - logo slot", () => {
  it("shows the small logo from the start on every normal page", () => {
    const { container } = renderShell();

    const slot = container.querySelector(".app-sidebar__logo-slot");
    expect(slot?.getAttribute("data-hidden")).toBe("false");
    expect(screen.getByRole("link", { name: "NINFA - vai a Oggi" })).not.toBeNull();
  });

  it("keeps the slot's box but empties it while the Home's hero logo is on screen", () => {
    const { container } = renderShell({ logoInitiallyHidden: true });

    expect(container.querySelector(".app-sidebar__logo-slot")?.getAttribute("data-hidden")).toBe(
      "true",
    );
  });

  it("lets the Home reveal the small logo through the shell context", async () => {
    function Reveal() {
      const { setHidden } = useShellLogo();
      return (
        <button type="button" onClick={() => setHidden(false)}>
          reveal
        </button>
      );
    }
    const user = userEvent.setup();
    const { container } = render(
      <AppShell
        properties={[]}
        selectedPropertyId=""
        onSelectProperty={vi.fn()}
        onLoggedOut={vi.fn()}
        activeSection="oggi"
        logoInitiallyHidden
      >
        <Reveal />
      </AppShell>,
    );
    expect(container.querySelector(".app-sidebar__logo-slot")?.getAttribute("data-hidden")).toBe(
      "true",
    );

    await user.click(screen.getByRole("button", { name: "reveal" }));

    expect(container.querySelector(".app-sidebar__logo-slot")?.getAttribute("data-hidden")).toBe(
      "false",
    );
  });
});
