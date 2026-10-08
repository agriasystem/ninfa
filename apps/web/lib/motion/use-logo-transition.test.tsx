// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FADE_MS, useLogoTransition } from "./use-logo-transition";

function stubMatchMedia(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduced && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width, writable: true });
}

beforeEach(() => {
  setViewportWidth(1440);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useLogoTransition", () => {
  it("starts idle, with no mode", () => {
    const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));

    expect(result.current.phase).toBe("idle");
    expect(result.current.mode).toBeNull();
  });

  it("runs the canvas trail on a normal desktop (no matchMedia at all, as in jsdom)", () => {
    const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));

    act(() => result.current.trigger());

    expect(result.current.phase).toBe("morphing");
    expect(result.current.mode).toBe("trail");
  });

  it("only the FIRST trigger ever starts a transition - later ones are no-ops", () => {
    const reveal = vi.fn();
    const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));

    act(() => {
      result.current.trigger();
      result.current.trigger();
      result.current.trigger();
    });
    expect(result.current.phase).toBe("morphing");

    act(() => result.current.trail.onDone());
    expect(result.current.phase).toBe("settled");
    act(() => result.current.trigger()); // the logo never comes back and never re-animates
    expect(result.current.phase).toBe("settled");
    expect(result.current.mode).toBe("trail");
    expect(reveal).toHaveBeenCalledTimes(1);
  });

  it("reveals the sidebar logo on arrival, then settles when the trail is done", () => {
    const reveal = vi.fn();
    const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));
    act(() => result.current.trigger());

    act(() => result.current.trail.onArrive());
    expect(reveal).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("morphing");

    act(() => result.current.trail.onDone());
    expect(result.current.phase).toBe("settled");
  });

  it("fades the HERO logo with the trail's own progress, through the element - never React state", () => {
    const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));
    const hero = document.createElement("img");
    result.current.heroRef.current = hero;

    act(() => result.current.trail.onProgress(0));
    expect(hero.style.opacity).toBe("1");
    act(() => result.current.trail.onProgress(0.5));
    expect(hero.style.opacity).toBe("0");
  });

  describe("reduced motion", () => {
    it("never animates: an immediate swap, no canvas mode, sidebar logo revealed at once", () => {
      stubMatchMedia(true);
      const reveal = vi.fn();
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));

      act(() => result.current.trigger());

      expect(result.current.phase).toBe("settled");
      expect(result.current.mode).toBe("fade"); // never "trail"
      expect(reveal).toHaveBeenCalledTimes(1);
    });

    it("still runs the trail when the user has NO reduced-motion preference", () => {
      stubMatchMedia(false);
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));

      act(() => result.current.trigger());

      expect(result.current.mode).toBe("trail");
    });
  });

  describe("small viewport", () => {
    it("uses a ~150 ms fade, never the canvas, then settles", () => {
      vi.useFakeTimers();
      setViewportWidth(600);
      const reveal = vi.fn();
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));

      act(() => result.current.trigger());
      expect(result.current.phase).toBe("morphing");
      expect(result.current.mode).toBe("fade");
      expect(reveal).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(FADE_MS - 1);
      });
      expect(result.current.phase).toBe("morphing");
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(result.current.phase).toBe("settled");
      expect(reveal).toHaveBeenCalledTimes(1);
    });

    it("is the same fade at exactly the 768px threshold boundary below it (767) and the trail from 768", () => {
      setViewportWidth(767);
      const small = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));
      act(() => small.result.current.trigger());
      expect(small.result.current.mode).toBe("fade");

      setViewportWidth(768);
      const wide = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));
      act(() => wide.result.current.trigger());
      expect(wide.result.current.mode).toBe("trail");
    });
  });

  describe("unavailable canvas", () => {
    it("degrades a started trail to the fade, and settles", () => {
      vi.useFakeTimers();
      const reveal = vi.fn();
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));
      act(() => result.current.trigger());
      expect(result.current.mode).toBe("trail");

      act(() => result.current.trail.onUnavailable());
      expect(result.current.mode).toBe("fade");
      act(() => {
        vi.advanceTimersByTime(FADE_MS);
      });

      expect(result.current.phase).toBe("settled");
      expect(reveal).toHaveBeenCalledTimes(1);
    });

    it("ignores an 'unavailable' report when no transition was ever triggered", () => {
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: vi.fn() }));

      act(() => result.current.trail.onUnavailable());

      expect(result.current.phase).toBe("idle");
    });

    it("a repeated 'unavailable' report (StrictMode) restarts nothing twice", () => {
      vi.useFakeTimers();
      const reveal = vi.fn();
      const { result } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));
      act(() => result.current.trigger());

      act(() => {
        result.current.trail.onUnavailable();
        result.current.trail.onUnavailable();
      });
      act(() => {
        vi.advanceTimersByTime(FADE_MS * 3);
      });

      expect(reveal).toHaveBeenCalledTimes(1);
    });
  });

  it("cleans its fade timer on unmount: nothing fires afterwards", () => {
    vi.useFakeTimers();
    setViewportWidth(500);
    const reveal = vi.fn();
    const { result, unmount } = renderHook(() => useLogoTransition({ revealSidebarLogo: reveal }));
    act(() => result.current.trigger());

    unmount();
    act(() => {
      vi.advanceTimersByTime(FADE_MS * 5);
    });

    expect(reveal).not.toHaveBeenCalled();
  });

  it("always calls the LATEST revealSidebarLogo (no stale closure)", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result, rerender } = renderHook(
      ({ reveal }) => useLogoTransition({ revealSidebarLogo: reveal }),
      { initialProps: { reveal: first } },
    );
    act(() => result.current.trigger());
    rerender({ reveal: second });

    act(() => result.current.trail.onArrive());

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
