// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PropertyAccess } from "@ninfa/contracts";

import { AppShell } from "./app-shell";

const useSessionMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));

function property(id: string, name: string): PropertyAccess {
  return { id, name, slug: name.toLowerCase(), timezone: "Europe/Rome" };
}

const noSession = { session: null, logout: vi.fn() };

describe("AppShell", () => {
  it("shows the NINFA wordmark, the account email, a logout action, and the page content", () => {
    useSessionMock.mockReturnValue({
      session: {
        user: { id: "u1", email: "a@b.c", display_name: null },
        session: { expires_at: "2026-12-31T00:00:00Z" },
        workspaces: [],
      },
      logout: vi.fn(),
    });

    render(
      <AppShell
        properties={[property("p1", "Masseria Ninfa")]}
        selectedPropertyId="p1"
        onSelectProperty={vi.fn()}
        onLoggedOut={vi.fn()}
      >
        <div>oggi content</div>
      </AppShell>,
    );

    expect(screen.getByText("NINFA")).not.toBeNull();
    expect(screen.getByText("a@b.c")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Esci" })).not.toBeNull();
    expect(screen.getByText("oggi content")).not.toBeNull();
  });

  it("never links to a feature that does not exist yet", () => {
    useSessionMock.mockReturnValue(noSession);

    const { container } = render(
      <AppShell properties={[]} selectedPropertyId="" onSelectProperty={vi.fn()} onLoggedOut={vi.fn()}>
        <div />
      </AppShell>,
    );

    for (const forbidden of [
      "Analytics",
      "Revenue",
      "Costi",
      "Personale",
      "Settings",
      "Notifications",
      "Ask NINFA",
    ]) {
      expect(container.textContent).not.toContain(forbidden);
    }
  });

  it("logout calls session.logout() and then onLoggedOut", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    const onLoggedOut = vi.fn();
    useSessionMock.mockReturnValue({
      session: {
        user: { id: "u1", email: "a@b.c", display_name: null },
        session: { expires_at: "2026-12-31T00:00:00Z" },
        workspaces: [],
      },
      logout,
    });
    const user = userEvent.setup();

    render(
      <AppShell properties={[]} selectedPropertyId="" onSelectProperty={vi.fn()} onLoggedOut={onLoggedOut}>
        <div />
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "Esci" }));

    expect(logout).toHaveBeenCalledOnce();
    expect(onLoggedOut).toHaveBeenCalledOnce();
  });

  it("shows the property selector only when there is more than one accessible property", () => {
    useSessionMock.mockReturnValue(noSession);

    const { rerender } = render(
      <AppShell
        properties={[property("p1", "A")]}
        selectedPropertyId="p1"
        onSelectProperty={vi.fn()}
        onLoggedOut={vi.fn()}
      >
        <div />
      </AppShell>,
    );
    expect(screen.queryByLabelText("Struttura")).toBeNull();

    rerender(
      <AppShell
        properties={[property("p1", "A"), property("p2", "B")]}
        selectedPropertyId="p1"
        onSelectProperty={vi.fn()}
        onLoggedOut={vi.fn()}
      >
        <div />
      </AppShell>,
    );
    expect(screen.getByLabelText("Struttura")).not.toBeNull();
  });
});
