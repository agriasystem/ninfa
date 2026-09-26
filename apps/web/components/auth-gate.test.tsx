// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthGate } from "./auth-gate";

const useSessionMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));

describe("AuthGate", () => {
  it("shows a neutral loading state while the session status is unknown - never authenticated content", () => {
    useSessionMock.mockReturnValue({ status: "loading" });

    render(
      <AuthGate onUnauthenticated={vi.fn()}>
        <div>secret content</div>
      </AuthGate>,
    );

    expect(screen.queryByText("secret content")).toBeNull();
  });

  it("renders children once a real session is confirmed", () => {
    useSessionMock.mockReturnValue({ status: "authenticated" });

    render(
      <AuthGate onUnauthenticated={vi.fn()}>
        <div>secret content</div>
      </AuthGate>,
    );

    expect(screen.getByText("secret content")).not.toBeNull();
  });

  it("calls onUnauthenticated and never renders children when there is no session", async () => {
    useSessionMock.mockReturnValue({ status: "unauthenticated" });
    const onUnauthenticated = vi.fn();

    render(
      <AuthGate onUnauthenticated={onUnauthenticated}>
        <div>secret content</div>
      </AuthGate>,
    );

    await waitFor(() => expect(onUnauthenticated).toHaveBeenCalledOnce());
    expect(screen.queryByText("secret content")).toBeNull();
  });
});
