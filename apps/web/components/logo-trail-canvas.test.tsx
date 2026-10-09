// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { StrictMode, createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sampleLogoPixelsMock = vi.fn();
const startLogoTrailMock = vi.fn();

vi.mock("@/lib/motion/logo-trail", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/motion/logo-trail")>();
  return {
    ...actual,
    sampleLogoPixels: (...args: unknown[]) => sampleLogoPixelsMock(...args),
    startLogoTrail: (...args: unknown[]) => startLogoTrailMock(...args),
  };
});

import { LogoTrailCanvas, type LogoTrailCanvasProps } from "./logo-trail-canvas";

function rect(left: number, top: number, width: number, height: number): DOMRect {
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

function elements(heroRect: DOMRect | null = rect(900, 200, 90, 114), slotRect = rect(46, 50, 32, 41)) {
  const hero = document.createElement("img");
  const slot = document.createElement("div");
  hero.getBoundingClientRect = () => heroRect ?? rect(0, 0, 0, 0);
  slot.getBoundingClientRect = () => slotRect;
  return { hero, slot };
}

function props(overrides: Partial<LogoTrailCanvasProps> = {}) {
  const { hero, slot } = elements();
  const heroRef = createRef<HTMLImageElement>();
  const slotRef = createRef<HTMLElement>();
  (heroRef as { current: HTMLImageElement | null }).current = hero;
  (slotRef as { current: HTMLElement | null }).current = slot;
  return {
    heroRef,
    slotRef,
    onProgress: vi.fn(),
    onArrive: vi.fn(),
    onDone: vi.fn(),
    onUnavailable: vi.fn(),
    ...overrides,
  } satisfies LogoTrailCanvasProps;
}

beforeEach(() => {
  sampleLogoPixelsMock.mockReset().mockReturnValue(
    Array.from({ length: 30 }, (_, index) => ({ u: (index % 6) / 6, v: index / 30, colour: "rgb(10,80,240)" })),
  );
  startLogoTrailMock.mockReset().mockReturnValue(vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LogoTrailCanvas - the overlay", () => {
  it("is aria-hidden decoration, a real <canvas> that exists only while mounted", () => {
    const { container, unmount } = render(<LogoTrailCanvas {...props()} />);

    const canvas = container.querySelector("canvas");
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(canvas?.className).toContain("logo-trail-canvas");
    unmount();
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("measures the REAL hero logo and slot boxes and sizes/places itself around them", () => {
    const { container } = render(<LogoTrailCanvas {...props()} />);

    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    // left/top: min of both boxes minus the margin, clamped at the viewport origin.
    expect(canvas.style.left).toBe("0px");
    expect(canvas.style.top).toBe("0px");
    // right/bottom: max of both boxes plus the margin (990+140, 314+140) - far from any constant.
    expect(canvas.style.width).toBe("1130px");
    expect(canvas.style.height).toBe("454px");
    expect(startLogoTrailMock).toHaveBeenCalledOnce();
    const options = startLogoTrailMock.mock.calls[0]?.[0] as {
      width: number;
      height: number;
      scene: { endScale: number; end: { x: number; y: number } };
    };
    expect(options.width).toBe(1130);
    expect(options.height).toBe(454);
    expect(options.scene.endScale).toBeCloseTo(41 / 114, 6); // slot height / hero height
    expect(options.scene.end).toEqual({ x: 46 + 16, y: 50 + 20.5 }); // the slot's centre
  });

  it("caps the device pixel ratio at 2", () => {
    vi.stubGlobal("devicePixelRatio", 3);
    render(<LogoTrailCanvas {...props()} />);

    expect((startLogoTrailMock.mock.calls[0]?.[0] as { dpr: number }).dpr).toBe(2);
  });

  it("keeps a low device pixel ratio as it is", () => {
    vi.stubGlobal("devicePixelRatio", 1);
    render(<LogoTrailCanvas {...props()} />);

    expect((startLogoTrailMock.mock.calls[0]?.[0] as { dpr: number }).dpr).toBe(1);
  });

  it("forwards the trail's progress / arrive / done to the parent, once the loop reports them", () => {
    const p = props();
    render(<LogoTrailCanvas {...p} />);
    const options = startLogoTrailMock.mock.calls[0]?.[0] as {
      onProgress: (t: number) => void;
      onArrive: () => void;
      onDone: () => void;
    };

    options.onProgress(0.4);
    options.onArrive();
    options.onDone();

    expect(p.onProgress).toHaveBeenCalledWith(0.4);
    expect(p.onArrive).toHaveBeenCalledOnce();
    expect(p.onDone).toHaveBeenCalledOnce();
    expect(p.onUnavailable).not.toHaveBeenCalled();
  });
});

describe("LogoTrailCanvas - cleanup", () => {
  it("cancels the animation when it unmounts mid-flight", () => {
    const cancel = vi.fn();
    startLogoTrailMock.mockReturnValue(cancel);
    const { unmount } = render(<LogoTrailCanvas {...props()} />);
    expect(cancel).not.toHaveBeenCalled();

    unmount();

    expect(cancel).toHaveBeenCalledOnce();
  });

  it("is StrictMode-safe: the throw-away first run is cancelled, the second keeps going", () => {
    const cancels: ReturnType<typeof vi.fn>[] = [];
    startLogoTrailMock.mockImplementation(() => {
      const cancel = vi.fn();
      cancels.push(cancel);
      return cancel;
    });

    const { unmount } = render(
      <StrictMode>
        <LogoTrailCanvas {...props()} />
      </StrictMode>,
    );

    expect(startLogoTrailMock).toHaveBeenCalledTimes(2);
    expect(cancels[0]).toHaveBeenCalledOnce(); // the discarded run is stopped...
    expect(cancels[1]).not.toHaveBeenCalled(); // ...the live one is not
    unmount();
    expect(cancels[1]).toHaveBeenCalledOnce();
  });
});

describe("LogoTrailCanvas - safe fallbacks (reported, never thrown)", () => {
  it("reports 'unavailable' when the hero logo is not there", () => {
    const p = props();
    (p.heroRef as { current: HTMLImageElement | null }).current = null;
    render(<LogoTrailCanvas {...p} />);

    expect(p.onUnavailable).toHaveBeenCalled();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("reports 'unavailable' when the sidebar slot is not there", () => {
    const p = props();
    (p.slotRef as { current: HTMLElement | null }).current = null;
    render(<LogoTrailCanvas {...p} />);

    expect(p.onUnavailable).toHaveBeenCalled();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("reports 'unavailable' for zero-sized geometry (jsdom, a hidden element)", () => {
    const { hero, slot } = elements(null);
    const p = props();
    (p.heroRef as { current: HTMLImageElement | null }).current = hero;
    (p.slotRef as { current: HTMLElement | null }).current = slot;
    render(<LogoTrailCanvas {...p} />);

    expect(p.onUnavailable).toHaveBeenCalled();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("reports 'unavailable' when the logo cannot be sampled (not decoded, blocked, jsdom)", () => {
    sampleLogoPixelsMock.mockReturnValue(null);
    const p = props();
    render(<LogoTrailCanvas {...p} />);

    expect(p.onUnavailable).toHaveBeenCalled();
    expect(startLogoTrailMock).not.toHaveBeenCalled();
  });

  it("reports 'unavailable' when the canvas has no 2D context (startLogoTrail answers null)", () => {
    startLogoTrailMock.mockReturnValue(null);
    const p = props();
    render(<LogoTrailCanvas {...p} />);

    expect(p.onUnavailable).toHaveBeenCalled();
    expect(p.onDone).not.toHaveBeenCalled();
  });
});
