// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/lib/session/session-context";

import { LoginForm } from "./login-form";

const loginMock = vi.fn();
const getSessionMock = vi.fn();
const logoutMock = vi.fn();

vi.mock("@/lib/api/auth", () => ({
  login: (...args: unknown[]) => loginMock(...args),
  getSession: (...args: unknown[]) => getSessionMock(...args),
  logout: (...args: unknown[]) => logoutMock(...args),
}));

beforeEach(() => {
  loginMock.mockReset();
  getSessionMock.mockReset().mockResolvedValue({
    ok: false,
    status: 401,
    code: "AUTHENTICATION_REQUIRED",
    message: "Authentication is required",
  });
  logoutMock.mockReset();
});

function renderForm(onSuccess: () => void = vi.fn()) {
  return render(
    <SessionProvider>
      <LoginForm onSuccess={onSuccess} />
    </SessionProvider>,
  );
}

describe("LoginForm", () => {
  it("has properly labelled email and password fields with the right autocomplete hints", () => {
    renderForm();

    const email = screen.getByLabelText("Email") as HTMLInputElement;
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(email.type).toBe("email");
    expect(email.autocomplete).toBe("email");
    expect(password.type).toBe("password");
    expect(password.autocomplete).toBe("current-password");
  });

  it("logs in, adopts the returned session, and calls onSuccess - never re-fetches getSession", async () => {
    const sessionContext = {
      user: { id: "u1", email: "a@b.c", display_name: null },
      session: { expires_at: "2026-12-31T00:00:00Z" },
      workspaces: [],
    };
    loginMock.mockResolvedValue({ ok: true, data: sessionContext });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderForm(onSuccess);

    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "a-real-passphrase-1234");
    await user.click(screen.getByRole("button", { name: "Accedi" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    expect(loginMock).toHaveBeenCalledWith({ email: "a@b.c", password: "a-real-passphrase-1234" });
    // getSessionMock was only called once, by SessionProvider's own bootstrap on mount - login
    // success must not trigger a second one.
    expect(getSessionMock).toHaveBeenCalledOnce();
  });

  it("shows the generic Italian error on invalid credentials - never a specific reason", async () => {
    loginMock.mockResolvedValue({
      ok: false,
      status: 401,
      code: "INVALID_CREDENTIALS",
      message: "Invalid email or password",
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Accedi" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Email o password non corretti.");
    expect(alert.textContent).not.toMatch(/unknown|inesistente|bloccat|locked/i);
  });

  it("shows a generic retry copy for a network/unexpected error, not the raw backend message", async () => {
    loginMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "Failed to fetch" });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "whatever-password");
    await user.click(screen.getByRole("button", { name: "Accedi" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toBe("Failed to fetch");
  });

  it("clears the password field after a failed submit - never keeps it around", async () => {
    loginMock.mockResolvedValue({
      ok: false,
      status: 401,
      code: "INVALID_CREDENTIALS",
      message: "Invalid email or password",
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Accedi" }));

    await screen.findByRole("alert");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
  });

  it("disables the submit button while a login request is in flight (blocks a double submit)", async () => {
    let resolveLogin!: (value: unknown) => void;
    loginMock.mockReturnValue(new Promise((resolve) => (resolveLogin = resolve)));
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderForm(onSuccess);

    await user.type(screen.getByLabelText("Email"), "a@b.c");
    await user.type(screen.getByLabelText("Password"), "a-real-passphrase-1234");
    const button = screen.getByRole("button", { name: "Accedi" });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: "Accesso in corso…" })); // a second click, ignored

    expect(
      (screen.getByRole("button", { name: "Accesso in corso…" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(loginMock).toHaveBeenCalledOnce(); // the second click never triggered a second request

    resolveLogin({
      ok: true,
      data: {
        user: { id: "u1", email: "a@b.c", display_name: null },
        session: { expires_at: "2026-12-31T00:00:00Z" },
        workspaces: [],
      },
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
  });
});
