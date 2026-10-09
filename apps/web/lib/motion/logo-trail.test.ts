// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import {
  TRAIL_ARRIVE_AT,
  TRAIL_DURATION_MS,
  buildEnergyLines,
  buildParticles,
  createTrailPath,
  drawTrailFrame,
  heroOpacityAt,
  sampleLogoPixels,
  seededRandom,
  startLogoTrail,
  type LogoSample,
  type TrailScene,
} from "./logo-trail";

/** A canvas 2D context that records what was drawn and never touches a real canvas. */
function recordingContext() {
  const gradient = { addColorStop: vi.fn() };
  const ctx = {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    setTransform: vi.fn(),
    createRadialGradient: vi.fn(() => gradient),
    globalAlpha: 1,
    lineWidth: 1,
    lineCap: "butt",
    lineJoin: "miter",
    strokeStyle: "",
    fillStyle: "",
  };
  return ctx;
}

function fakeCanvas(ctx: ReturnType<typeof recordingContext> | null) {
  return {
    width: 0,
    height: 0,
    getContext: vi.fn(() => ctx),
  } as unknown as HTMLCanvasElement & { getContext: ReturnType<typeof vi.fn> };
}

const START = { x: 900, y: 300 };
const END = { x: 60, y: 70 };

function scene(): TrailScene {
  const random = seededRandom(11);
  const samples: LogoSample[] = Array.from({ length: 60 }, (_, index) => ({
    u: (index % 10) / 10,
    v: Math.floor(index / 10) / 6,
    colour: "rgb(20,80,240)",
  }));
  const hero = { x: 850, y: 245, width: 100, height: 110 };
  return {
    particles: buildParticles(samples, hero, random),
    path: createTrailPath(START, END),
    endScale: 0.37,
    end: END,
    unit: hero.width / 78,
    lines: buildEnergyLines(random, hero.width / 78),
  };
}

describe("createTrailPath", () => {
  it("starts at the hero logo and ends exactly at the sidebar slot", () => {
    const path = createTrailPath(START, END);
    expect(path.at(0)).toEqual(START);
    expect(path.at(1).x).toBeCloseTo(END.x, 6);
    expect(path.at(1).y).toBeCloseTo(END.y, 6);
  });

  it("rises first, then sweeps left near the top (the approved arc), for ANY geometry", () => {
    for (const [from, to] of [
      [START, END],
      [
        { x: 500, y: 200 },
        { x: 40, y: 60 },
      ],
    ] as const) {
      const path = createTrailPath(from, to);
      expect(path.at(0.15).y).toBeLessThan(from.y); // it climbs above the logo before leaving
      expect(path.at(0.5).x).toBeLessThan(from.x);
      expect(path.at(0.5).y).toBeLessThan(from.y);
    }
  });

  it("has a unit tangent everywhere", () => {
    const path = createTrailPath(START, END);
    for (const s of [0, 0.25, 0.5, 0.75, 1]) {
      const tangent = path.tangent(s);
      expect(Math.hypot(tangent.x, tangent.y)).toBeCloseTo(1, 6);
    }
  });

  it("uses only the given geometry (no hidden 1672x941 coordinates)", () => {
    const small = createTrailPath({ x: 100, y: 100 }, { x: 10, y: 10 });
    expect(small.at(0)).toEqual({ x: 100, y: 100 });
    expect(Math.max(...[0.2, 0.4, 0.6, 0.8].map((s) => small.at(s).x))).toBeLessThan(120);
  });
});

describe("heroOpacityAt", () => {
  it("keeps the hero logo until the particles take it, then removes it - never both", () => {
    expect(heroOpacityAt(0)).toBe(1);
    expect(heroOpacityAt(0.08)).toBe(1);
    expect(heroOpacityAt(0.26)).toBe(0);
    expect(heroOpacityAt(1)).toBe(0);
    let previous = 1;
    for (let t = 0; t <= 1; t += 0.02) {
      const value = heroOpacityAt(t);
      expect(value).toBeLessThanOrEqual(previous + 1e-9);
      previous = value;
    }
  });
});

describe("seededRandom", () => {
  it("is deterministic per seed and stays inside [0, 1)", () => {
    const a = seededRandom(11);
    const b = seededRandom(11);
    for (let i = 0; i < 50; i += 1) {
      const value = a();
      expect(value).toBe(b());
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
    expect(seededRandom(12)()).not.toBe(seededRandom(11)());
  });
});

describe("buildParticles", () => {
  const samples: LogoSample[] = [
    { u: 0.1, v: 0.1, colour: "rgb(1,2,3)" },
    { u: 0.9, v: 0.9, colour: "rgb(4,5,6)" },
    { u: 0.5, v: 0.5, colour: "rgb(7,8,9)" },
  ];
  const hero = { x: 0, y: 0, width: 100, height: 120 };

  it("makes one particle per sample, keeping the logo's own pixel colour", () => {
    const particles = buildParticles(samples, hero, seededRandom(11));
    expect(particles.map((particle) => particle.col)).toEqual(["rgb(1,2,3)", "rgb(4,5,6)", "rgb(7,8,9)"]);
  });

  it("places each particle relative to the logo centre, at the logo's real size", () => {
    const [first, second] = buildParticles(samples, hero, seededRandom(11));
    expect(first?.lx).toBeCloseTo(-40, 6);
    expect(first?.ly).toBeCloseTo(-48, 6);
    expect(second?.lx).toBeCloseTo(40, 6);
    expect(second?.ly).toBeCloseTo(48, 6);
  });

  it("is deterministic and releases the upper-left of the logo before the lower-right", () => {
    const a = buildParticles(samples, hero, seededRandom(11));
    const b = buildParticles(samples, hero, seededRandom(11));
    expect(a).toEqual(b);
    expect((a[0]?.r ?? 1)).toBeLessThan(a[1]?.r ?? 0);
  });
});

describe("sampleLogoPixels", () => {
  function image(complete: boolean, naturalWidth = 448, naturalHeight = 568) {
    return { complete, naturalWidth, naturalHeight } as HTMLImageElement;
  }

  function withScratchContext(context: unknown) {
    const original = document.createElement.bind(document);
    return vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "canvas") {
        return { width: 0, height: 0, getContext: () => context } as unknown as HTMLCanvasElement;
      }
      return original(tag);
    });
  }

  it("returns null while the logo is not decoded yet (the caller falls back to a fade)", () => {
    expect(sampleLogoPixels(image(false), 100, seededRandom(1))).toBeNull();
    expect(sampleLogoPixels(image(true, 0, 0), 100, seededRandom(1))).toBeNull();
  });

  it("returns null when there is no 2D context (jsdom, a blocked canvas)", () => {
    const spy = withScratchContext(null);
    try {
      expect(sampleLogoPixels(image(true), 100, seededRandom(1))).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });

  it("returns null when reading pixels is refused", () => {
    const spy = withScratchContext({
      drawImage: vi.fn(),
      getImageData: () => {
        throw new Error("tainted");
      },
    });
    try {
      expect(sampleLogoPixels(image(true), 100, seededRandom(1))).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });

  it("returns null for an (almost) empty logo", () => {
    const spy = withScratchContext({
      drawImage: vi.fn(),
      getImageData: (_x: number, _y: number, w: number, h: number) => ({
        data: new Uint8ClampedArray(w * h * 4), // fully transparent
      }),
    });
    try {
      expect(sampleLogoPixels(image(true), 100, seededRandom(1))).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });

  it("samples only opaque pixels, with their own colour, inside the unit square", () => {
    const spy = withScratchContext({
      drawImage: vi.fn(),
      getImageData: (_x: number, _y: number, w: number, h: number) => {
        const data = new Uint8ClampedArray(w * h * 4);
        // Only the left half is opaque, pure red.
        for (let y = 0; y < h; y += 1) {
          for (let x = 0; x < w / 2; x += 1) {
            const o = (y * w + x) * 4;
            data[o] = 255;
            data[o + 3] = 255;
          }
        }
        return { data };
      },
    });
    try {
      const samples = sampleLogoPixels(image(true), 200, seededRandom(1));
      expect(samples).toHaveLength(200);
      for (const sample of samples ?? []) {
        expect(sample.colour).toBe("rgb(255,0,0)");
        expect(sample.u).toBeGreaterThanOrEqual(0);
        expect(sample.u).toBeLessThanOrEqual(0.5 + 1 / 96);
        expect(sample.v).toBeGreaterThanOrEqual(0);
        expect(sample.v).toBeLessThanOrEqual(1);
      }
    } finally {
      spy.mockRestore();
    }
  });
});

describe("drawTrailFrame", () => {
  it("draws nothing before the trail begins (only a clear)", () => {
    const ctx = recordingContext();
    drawTrailFrame(ctx as unknown as CanvasRenderingContext2D, scene(), 1000, 400, 0.05);
    expect(ctx.clearRect).toHaveBeenCalledOnce();
    expect(ctx.stroke).not.toHaveBeenCalled();
  });

  it("draws the ribbon and particles mid-flight, then restores the global alpha", () => {
    const ctx = recordingContext();
    drawTrailFrame(ctx as unknown as CanvasRenderingContext2D, scene(), 1000, 400, 0.5);
    expect(ctx.stroke.mock.calls.length).toBeGreaterThan(50);
    expect(ctx.globalAlpha).toBe(1);
  });

  it("draws the landing bloom near the end", () => {
    const ctx = recordingContext();
    drawTrailFrame(ctx as unknown as CanvasRenderingContext2D, scene(), 1000, 400, 0.85);
    expect(ctx.createRadialGradient).toHaveBeenCalled();
    expect(ctx.fillRect).toHaveBeenCalled();
  });

  it("is a pure function of (scene, t): the same input draws the same strokes", () => {
    const a = recordingContext();
    const b = recordingContext();
    const s = scene();
    drawTrailFrame(a as unknown as CanvasRenderingContext2D, s, 1000, 400, 0.6);
    drawTrailFrame(b as unknown as CanvasRenderingContext2D, s, 1000, 400, 0.6);
    expect(a.moveTo.mock.calls).toEqual(b.moveTo.mock.calls);
    expect(a.lineTo.mock.calls).toEqual(b.lineTo.mock.calls);
  });
});

describe("startLogoTrail", () => {
  function harness() {
    const frames: (() => void)[] = [];
    let time = 0;
    return {
      now: () => time,
      requestFrame: vi.fn((callback: () => void) => {
        frames.push(callback);
        return frames.length;
      }),
      cancelFrame: vi.fn(),
      advance(ms: number) {
        time += ms;
        const next = frames.shift();
        next?.();
      },
      pending: () => frames.length,
    };
  }

  it("returns null when the canvas has no 2D context (the caller falls back to a fade)", () => {
    const h = harness();
    const result = startLogoTrail({
      canvas: fakeCanvas(null),
      scene: scene(),
      width: 800,
      height: 400,
      dpr: 2,
      now: h.now,
      requestFrame: h.requestFrame,
      cancelFrame: h.cancelFrame,
    });
    expect(result).toBeNull();
    expect(h.requestFrame).not.toHaveBeenCalled();
  });

  it("sizes the canvas in device pixels from the (already capped) dpr", () => {
    const h = harness();
    const canvas = fakeCanvas(recordingContext());
    startLogoTrail({
      canvas,
      scene: scene(),
      width: 800,
      height: 400,
      dpr: 2,
      now: h.now,
      requestFrame: h.requestFrame,
      cancelFrame: h.cancelFrame,
    });
    expect(canvas.width).toBe(1600);
    expect(canvas.height).toBe(800);
  });

  it("plays for about one second, arrives once, finishes once, with ONE frame loop", () => {
    const h = harness();
    const onProgress = vi.fn();
    const onArrive = vi.fn();
    const onDone = vi.fn();
    startLogoTrail({
      canvas: fakeCanvas(recordingContext()),
      scene: scene(),
      width: 800,
      height: 400,
      dpr: 1,
      onProgress,
      onArrive,
      onDone,
      now: h.now,
      requestFrame: h.requestFrame,
      cancelFrame: h.cancelFrame,
    });
    expect(TRAIL_DURATION_MS).toBe(1000);

    expect(h.pending()).toBe(1); // exactly one chain
    h.advance(100);
    expect(onArrive).not.toHaveBeenCalled();
    h.advance(300); // t = 0.4
    expect(h.pending()).toBe(1);
    h.advance(450); // t = 0.85 -> past TRAIL_ARRIVE_AT
    expect(TRAIL_ARRIVE_AT).toBe(0.8);
    expect(onArrive).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    h.advance(100);
    h.advance(100); // t = 1
    expect(onArrive).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(h.pending()).toBe(0); // the loop stops by itself

    const progress = onProgress.mock.calls.map(([t]) => t as number);
    expect(progress.length).toBeGreaterThan(3);
    expect([...progress].sort((a, b) => a - b)).toEqual(progress); // monotonic
    expect(progress.at(-1)).toBe(1);
  });

  it("cancel stops the loop for good: no further frame, no arrive, no done", () => {
    const h = harness();
    const onArrive = vi.fn();
    const onDone = vi.fn();
    const ctx = recordingContext();
    const cancel = startLogoTrail({
      canvas: fakeCanvas(ctx),
      scene: scene(),
      width: 800,
      height: 400,
      dpr: 1,
      onArrive,
      onDone,
      now: h.now,
      requestFrame: h.requestFrame,
      cancelFrame: h.cancelFrame,
    });
    h.advance(200);

    cancel?.();
    expect(h.cancelFrame).toHaveBeenCalledOnce();
    h.advance(1000); // the already-scheduled frame fires late

    expect(onArrive).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(h.pending()).toBe(0);
    expect(ctx.clearRect).toHaveBeenCalled(); // the canvas is left clean
  });

  it("cancel is idempotent", () => {
    const h = harness();
    const cancel = startLogoTrail({
      canvas: fakeCanvas(recordingContext()),
      scene: scene(),
      width: 800,
      height: 400,
      dpr: 1,
      now: h.now,
      requestFrame: h.requestFrame,
      cancelFrame: h.cancelFrame,
    });
    cancel?.();
    cancel?.();
    expect(h.cancelFrame).toHaveBeenCalledOnce();
  });
});
