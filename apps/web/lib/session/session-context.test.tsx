// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "./session-context";

const getSessionMock = vi.fn();
const logoutMock = vi.fn();

vi.mock("@/lib/api/auth", () => ({
  getSession: (...args: unknown[]) => getSessionMock(...args),
  logout: (...args: unknown[]) => logoutMock(...args),
}));

const sessionContext = {
  user: { id: "u1", email: "a@b.c", display_name: null },
  session: { expires_at: "2026-12-31T00:00:00Z" },
  workspaces: [],
};

function Probe() {
  const { status, session, logout } = useSession();
  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="email">{session?.user.email ?? ""}</div>
      <button
        onClick={() => {
          void logout();
        }}
      >
        logout
      </button>
    </div>
  );
}

beforeEach(() => {
  getSessionMock.mockReset();
  logoutMock.mockReset();
});

describe("SessionProvider", () => {
  it("starts in loading, then becomes authenticated once GET /auth/session answers 200", async () => {
    getSessionMock.mockResolvedValue({ ok: true, data: sessionContext });

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    expect(screen.getByTestId("status").textContent).toBe("loading");
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByTestId("email").textContent).toBe("a@b.c");
    expect(getSessionMock).toHaveBeenCalledOnce();
  });

  it("becomes unauthenticated when GET /auth/session answers 401", async () => {
    getSessionMock.mockResolvedValue({
      ok: false,
      status: 401,
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication is required",
    });

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("unauthenticated"));
    expect(screen.getByTestId("email").textContent).toBe("");
  });

  it("logout calls POST /auth/logout and clears local state, no token ever stored client-side", async () => {
    getSessionMock.mockResolvedValue({ ok: true, data: sessionContext });
    logoutMock.mockResolvedValue({ ok: true, data: undefined });

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));

    await act(async () => {
      screen.getByRole("button", { name: "logout" }).click();
    });

    expect(logoutMock).toHaveBeenCalledOnce();
    expect(screen.getByTestId("status").textContent).toBe("unauthenticated");
    expect(screen.getByTestId("email").textContent).toBe("");
  });

  it("throws a clear error when useSession is used outside a SessionProvider", () => {
    function Bare() {
      useSession();
      return null;
    }

    expect(() => render(<Bare />)).toThrow(/SessionProvider/);
  });
});
