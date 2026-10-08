// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { feed } from "@/test/home-support";

import { HomeScreen } from "./home-screen";
import { ShellLogoContext } from "./shell-logo-context";

const useSessionMock = vi.fn();
const getDecisionFeedMock = vi.fn();
const sampleLogoPixelsMock = vi.fn();
const startLogoTrailMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("@/lib/api/decisions", () => ({
  getDecisionFeed: (...args: unknown[]) => getDecisionFeedMock(...args),
}));
vi.mock("@/lib/api/ask-ninfa", () => ({ askMiaHome: vi.fn() }));
vi.mock("@/lib/motion/logo-trail", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/motion/logo-trail")>();
  return {
    ...actual,
    sampleLogoPixels: (...args: unknown[]) => sampleLogoPixelsMock(...args),
    startLogoTrail: (...args: unknown[]) => startLogoTrailMock(...args),
  };
});

interface TrailOptions {
  onProgress: (t: number) => void;
  onArrive: () => void;
  onDone: () => void;
}

function box(left: number, top: number, width: number, height: number): DOMRect {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  };
}

const setHidden = vi.fn();
let slot: HTMLDivElement;

function renderHome(strict = false) {
  const tree = (
    <ShellLogoContext.Provider value={{ slotRef: { current: slot }, setHidden }}>
      <HomeScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />
    </ShellLogoContext.Provider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

function mia() {
  return screen.getByRole("textbox", { name: "La tua domanda per Mia" }) as HTMLInputElement;
}

function homeRoot(container: HTMLElement) {
  return container.querySelector(".home") as HTMLElement;
}

function lastTrailOptions(): TrailOptions {
  return startLogoTrailMock.mock.calls.at(-1)?.[0] as TrailOptions;
}

function stubMatchMedia(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduced && query.includes("prefers-reduced-motion"),
      media: query,
    })),
  );
}

beforeEach(() => {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.classList.contains("home__logo")) return box(900, 150, 90, 114);
    if (this === slot) return box(46, 50, 32, 41);
    return box(0, 0, 0, 0);
  });
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440, writable: true });
  slot = document.createElement("div");
  document.body.appendChild(slot);
  useSessionMock.mockReturnValue({
    session: {
      user: { id: "u1", email: "a@b.c", display_name: "Giulia Rossi" },
      session: { expires_at: "2026-12-31T00:00:00Z" },
      workspaces: [],
    },
  });
  getDecisionFeedMock.mockReset().mockResolvedValue({
    ok: true,
    data: feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: "2026-10-08" }),
  });
  sampleLogoPixelsMock.mockReset().mockReturnValue(
    Array.from({ length: 30 }, (_, index) => ({ u: (index % 6) / 6, v: index / 30, colour: "rgb(10,80,240)" })),
  );
  startLogoTrailMock.mockReset().mockReturnValue(vi.fn());
  setHidden.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  slot.remove();
});

describe("Home logo - initial state", () => {
  it("shows the big hero logo, centred in the hero, and no canvas", async () => {
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("idle");
    expect(container.querySelector(".home__logo")).not.toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
    expect(setHidden).not.toHaveBeenCalled();
  });

  it("the hero logo is decorative: no alt text to announce", async () => {
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    expect(container.querySelector(".home__logo")?.getAttribute("alt")).toBe("");
  });
});

describe("Home logo - what does NOT start the transition", () => {
  it("focusing the Mia input does not", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.click(mia());
    await user.tab();
    await user.click(mia());

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("idle");
    expect(document.querySelector("canvas")).toBeNull();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("typing only whitespace does not", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "     ");

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("idle");
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });
});

describe("Home logo - the transition", () => {
  it("the first real character starts exactly ONE trail on a temporary, aria-hidden canvas", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao come stai");

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("morphing");
    const canvases = document.querySelectorAll("canvas");
    expect(canvases).toHaveLength(1);
    expect(canvases[0]?.getAttribute("aria-hidden")).toBe("true");
    expect(startLogoTrailMock).toHaveBeenCalledTimes(1);
  });

  it("pasting real text starts it too", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.click(mia());

    await user.paste("Ci sono altri problemi?");

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("morphing");
    expect(startLogoTrailMock).toHaveBeenCalledTimes(1);
  });

  it("a suggested question filling the input starts it as well (it is real text now)", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.click(screen.getByRole("button", { name: "Qual è la priorità più urgente oggi?" }));

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("morphing");
  });

  it("lands in the sidebar: reveals the small logo on arrival, removes the hero logo when done", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "C");

    act(() => lastTrailOptions().onArrive());
    expect(setHidden).toHaveBeenCalledWith(false);
    expect(container.querySelector(".home__logo")).not.toBeNull(); // still there until the end

    act(() => lastTrailOptions().onDone());
    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled");
    expect(container.querySelector(".home__logo")).toBeNull(); // the central logo is gone
    expect(document.querySelector("canvas")).toBeNull(); // and so is the canvas
  });

  it("fades the hero logo with the trail so it is never duplicated on screen", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "C");

    act(() => lastTrailOptions().onProgress(0.5));

    expect((container.querySelector(".home__logo") as HTMLElement).style.opacity).toBe("0");
  });

  it("keeps the greeting, the message and Mia on screen throughout", async () => {
    const user = userEvent.setup();
    renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "C");
    act(() => lastTrailOptions().onDone());

    expect(screen.getByText("Ciao Giulia,")).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Tutto sotto controllo");
    expect(mia().value).toBe("C");
  });

  it("clearing the input never reverses it, never restarts it", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "Ciao");
    act(() => lastTrailOptions().onDone());

    await user.clear(mia());
    await user.type(mia(), "Di nuovo");

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled");
    expect(container.querySelector(".home__logo")).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
    expect(startLogoTrailMock).toHaveBeenCalledTimes(1);
  });

  it("clearing mid-flight does not stop or reverse the transition either", async () => {
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "Ciao");

    await user.clear(mia());

    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("morphing");
    expect(document.querySelectorAll("canvas")).toHaveLength(1);
  });
});

describe("Home logo - cleanup", () => {
  it("StrictMode: still exactly one transition's worth of live animation", async () => {
    const cancels: ReturnType<typeof vi.fn>[] = [];
    startLogoTrailMock.mockImplementation(() => {
      const cancel = vi.fn();
      cancels.push(cancel);
      return cancel;
    });
    const user = userEvent.setup();
    renderHome(true);
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    expect(document.querySelectorAll("canvas")).toHaveLength(1);
    // The throw-away first run was cancelled; only the last one is still alive.
    const alive = cancels.filter((cancel) => cancel.mock.calls.length === 0);
    expect(alive).toHaveLength(1);
  });

  it("unmounting mid-flight cancels the loop and removes the canvas", async () => {
    const cancel = vi.fn();
    startLogoTrailMock.mockReturnValue(cancel);
    const user = userEvent.setup();
    const { unmount } = renderHome();
    await screen.findByText("Tutto sotto controllo");
    await user.type(mia(), "Ciao");
    expect(cancel).not.toHaveBeenCalled();

    unmount();

    expect(cancel).toHaveBeenCalledTimes(1);
    expect(document.querySelector("canvas")).toBeNull();
  });
});

describe("Home logo - safe fallbacks", () => {
  it("a canvas with no 2D context degrades to a plain fade and still lands", async () => {
    startLogoTrailMock.mockReturnValue(null); // `getContext('2d')` was null
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    await vi.waitFor(() => expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled"));
    expect(setHidden).toHaveBeenCalledWith(false);
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("a logo that cannot be sampled degrades to the fade too (never a half-drawn effect)", async () => {
    sampleLogoPixelsMock.mockReturnValue(null);
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    await vi.waitFor(() => expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled"));
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("with real jsdom (no canvas support at all) the transition still completes", async () => {
    // jsdom's own `getContext` is "not implemented" and answers null - the real production path
    // `startLogoTrail` takes when a browser blocks the canvas.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    startLogoTrailMock.mockImplementation(() => {
      const canvas = document.createElement("canvas");
      return canvas.getContext("2d") === null ? null : vi.fn();
    });
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    await vi.waitFor(() => expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled"));
  });
});

describe("Home logo - reduced motion and small viewports", () => {
  it("prefers-reduced-motion: NO canvas ever, an immediate swap, sidebar logo revealed", async () => {
    stubMatchMedia(true);
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    expect(document.querySelector("canvas")).toBeNull();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
    expect(sampleLogoPixelsMock).not.toHaveBeenCalled();
    expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled");
    expect(container.querySelector(".home__logo")).toBeNull();
    expect(setHidden).toHaveBeenCalledWith(false);
  });

  it("a small viewport: a simple fade - no canvas - then the logo has landed", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390, writable: true });
    const user = userEvent.setup();
    const { container } = renderHome();
    await screen.findByText("Tutto sotto controllo");

    await user.type(mia(), "Ciao");

    expect(document.querySelector("canvas")).toBeNull();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
    expect(container.querySelector(".home__logo--leaving")).not.toBeNull(); // fading out
    await vi.waitFor(() => expect(homeRoot(container).getAttribute("data-logo-phase")).toBe("settled"));
    expect(setHidden).toHaveBeenCalledWith(false);
  });
});
