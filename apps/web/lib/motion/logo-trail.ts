/**
 * The Home's logo transition (Home UI V1): the hero logo dissolves into a fluid ribbon of particles
 * that sweeps up and to the left and lands as the small logo at the top of the sidebar.
 *
 * Ported from the approved motion prototype (`docs/ui/references/home-v1/logo-animation.zip`,
 * `ninfa-scene.jsx`) - the CURVE, the per-particle release/lag/lateral-spread model, the ribbon and
 * the landing bloom - and deliberately NOT its scaffolding: no design-tool timeline player, no fixed
 * 1672x941 coordinates (every position here comes from real DOM geometry, given by the caller), no
 * traced SVG logo (particles are sampled from the OFFICIAL brand PNG itself, so their colours are the
 * logo's own), and none of the prototype's extras that read as busy rather than premium (the
 * triangular fragments). Zero dependencies: plain Canvas 2D.
 *
 * `drawTrailFrame` is a pure function of `(scene, t)`; `startLogoTrail` is the one place that owns a
 * `requestAnimationFrame` loop, and returns its own cancel function. Nothing here touches React.
 */

export interface Point {
  x: number;
  y: number;
}

/** A rectangle in the CANVAS' own coordinate space (CSS pixels). */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TrailParticle {
  /** Offset from the logo centre, at hero scale (CSS px). */
  lx: number;
  ly: number;
  /** Release time (0..1 of the whole transition) and its per-particle lag. */
  r: number;
  lag: number;
  /** Flight duration (fraction of the transition). */
  dur: number;
  /** Lateral / along-track spread of the particle while in flight (CSS px). */
  lat: number;
  al: number;
  ph: number;
  /** Size, base alpha, colour. */
  sz: number;
  a0: number;
  col: string;
  bright: boolean;
}

export interface TrailPath {
  at: (s: number) => Point;
  tangent: (s: number) => Point;
}

export interface TrailScene {
  particles: readonly TrailParticle[];
  path: TrailPath;
  /** Scale of the landed logo relative to the hero logo (`slot height / hero height`). */
  endScale: number;
  /** Where the logo lands (canvas space) - the landing bloom is centred here. */
  end: Point;
  /** Pixel scale of the whole effect, `hero logo width / 78` (the prototype's own logo width). */
  unit: number;
  lines: readonly EnergyLine[];
}

export interface EnergyLine {
  o: number;
  lag: number;
  len: number;
  a: number;
  w: number;
  col: string;
}

/** About one second, as specified. */
export const TRAIL_DURATION_MS = 1000;
/** From this progress on, the small logo is allowed to appear in the sidebar slot. */
export const TRAIL_ARRIVE_AT = 0.8;
/** The brand-blue tones of the ribbon itself (the prototype's own). */
const RIBBON_FAR = "#3f7bff";
const RIBBON_MID = "#2f6bff";
const RIBBON_CORE = "#8fd0ff";
const LINE_COLOURS = ["#1a55f5", "#2f7bff", "#5b8cff", "#8aa4ff", "#8b7dff", "#3fb0ff"];

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));
const smooth = (a: number, b: number, x: number): number => {
  const k = clamp01((x - a) / (b - a));
  return k * k * (3 - 2 * k);
};
const easeInOut = (x: number): number =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

/** Deterministic PRNG (mulberry32) - the same logo always produces the same trail. */
export function seededRandom(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Opacity of the HERO logo at progress `t`: it must be gone while the particles carry the logo
 * away, so the logo is never duplicated on screen (prototype: erased over t = 0.1 .. 0.26). */
export function heroOpacityAt(t: number): number {
  return 1 - smooth(0.08, 0.26, t);
}

/**
 * The cubic Bezier the logo travels: it rises first, then sweeps left near the top. Control points
 * are derived from the REAL start/end (the prototype's own 1672x941 numbers, expressed as
 * proportions of the travelled distance), so the same curve shape holds at any viewport size.
 */
export function createTrailPath(start: Point, end: Point): TrailPath {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const p1: Point = { x: start.x + dx * 0.02, y: start.y - Math.max(60, Math.abs(dy) * 0.4) };
  const p2: Point = { x: start.x + dx * 0.55, y: end.y - Math.max(20, Math.abs(dy) * 0.05) };
  const at = (s: number): Point => {
    const u = 1 - s;
    const a = u * u * u;
    const b = 3 * u * u * s;
    const c = 3 * u * s * s;
    const d = s * s * s;
    return {
      x: a * start.x + b * p1.x + c * p2.x + d * end.x,
      y: a * start.y + b * p1.y + c * p2.y + d * end.y,
    };
  };
  const tangent = (s: number): Point => {
    const u = 1 - s;
    const x = 3 * u * u * (p1.x - start.x) + 6 * u * s * (p2.x - p1.x) + 3 * s * s * (end.x - p2.x);
    const y = 3 * u * u * (p1.y - start.y) + 6 * u * s * (p2.y - p1.y) + 3 * s * s * (end.y - p2.y);
    const length = Math.hypot(x, y) || 1;
    return { x: x / length, y: y / length };
  };
  return { at, tangent };
}

export interface LogoSample {
  /** Position inside the logo image, 0..1. */
  u: number;
  v: number;
  colour: string;
}

/**
 * Picks `count` random OPAQUE pixels of the logo image (with their own colour). Returns `null` if the
 * image is not decoded yet, the 2D context is unavailable (jsdom) or reading pixels is refused - the
 * caller then falls back to a plain fade, never a half-drawn effect.
 */
export function sampleLogoPixels(
  image: HTMLImageElement,
  count: number,
  random: () => number,
): LogoSample[] | null {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (!image.complete || width === 0 || height === 0) return null;
  const columns = 96;
  const rows = Math.max(1, Math.round((columns * height) / width));
  const scratch = document.createElement("canvas");
  scratch.width = columns;
  scratch.height = rows;
  const ctx = scratch.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  let data: Uint8ClampedArray;
  try {
    ctx.drawImage(image, 0, 0, columns, rows);
    data = ctx.getImageData(0, 0, columns, rows).data;
  } catch {
    return null;
  }
  const opaque: number[] = [];
  for (let i = 0; i < columns * rows; i += 1) {
    if ((data[i * 4 + 3] ?? 0) > 140) opaque.push(i);
  }
  if (opaque.length < Math.max(20, count / 8)) return null;

  const samples: LogoSample[] = [];
  for (let n = 0; n < count; n += 1) {
    const cell = opaque[Math.floor(random() * opaque.length)] ?? 0;
    const r = data[cell * 4] ?? 0;
    const g = data[cell * 4 + 1] ?? 0;
    const b = data[cell * 4 + 2] ?? 0;
    samples.push({
      u: ((cell % columns) + random()) / columns,
      v: (Math.floor(cell / columns) + random()) / rows,
      colour: `rgb(${r},${g},${b})`,
    });
  }
  return samples;
}

/** Turns sampled logo pixels into flying particles, released from the upper-left of the logo first
 * (the prototype's own sweep order). `hero` is the hero logo's box in canvas space. */
export function buildParticles(
  samples: readonly LogoSample[],
  hero: Box,
  random: () => number,
): TrailParticle[] {
  const unit = hero.width / 78;
  const projections = samples.map((sample) => -0.25 * (sample.u - 0.5) * 78 - (sample.v - 0.5) * 86);
  const min = Math.min(...projections);
  const max = Math.max(...projections);
  const span = max - min || 1;
  return samples.map((sample, index) => {
    const order = 1 - ((projections[index] ?? 0) - min) / span;
    const z = 0.45 + random() * 1.15;
    return {
      lx: (sample.u - 0.5) * hero.width,
      ly: (sample.v - 0.5) * hero.height,
      r: 0.1 + 0.12 * order + random() * 0.012,
      lag: 0.02 + 0.12 * Math.pow(random(), 1.5),
      dur: 0.5 + random() * 0.04,
      lat: (random() + random() + random() - 1.5) * 15 * z * unit,
      al: (random() - 0.5) * 22 * unit,
      ph: random() * 6.28,
      sz: (0.7 + z * 1.05) * Math.min(1.6, Math.max(0.8, unit)),
      a0: 0.5 + random() * 0.45,
      col: sample.colour,
      bright: random() < 0.22,
    };
  });
}

export function buildEnergyLines(random: () => number, unit: number): EnergyLine[] {
  return Array.from({ length: 24 }, () => ({
    o: (random() - 0.5) * 40 * unit,
    lag: random() * 0.1,
    len: 0.08 + random() * 0.1,
    a: 0.3 + random() * 0.5,
    w: 0.6 + random() * 1.1,
    col: LINE_COLOURS[Math.floor(random() * LINE_COLOURS.length)] ?? RIBBON_MID,
  }));
}

interface Placed {
  x: number;
  y: number;
  s: number;
}

function place(particle: TrailParticle, scene: TrailScene, t: number, out: Placed): void {
  const s = easeInOut(clamp01((t - particle.r - particle.lag) / particle.dur));
  const centre = scene.path.at(s);
  const tangent = scene.path.tangent(s);
  const spread = smooth(0, 0.3, s);
  const gather = smooth(0.72, 1, s);
  const scale = 1 + (scene.endScale - 1) * s;
  const keepShape = 1 - spread + gather; // the logo shape holds at the start and re-forms at the end
  const flowing = spread * (1 - gather);
  const lateral =
    (particle.lat * (0.55 + 0.45 * Math.sin(s * Math.PI)) + Math.sin(s * 11 + particle.ph) * 2.2) *
    flowing;
  const along = particle.al * flowing;
  out.x = centre.x + particle.lx * scale * keepShape - tangent.y * lateral + tangent.x * along;
  out.y = centre.y + particle.ly * scale * keepShape + tangent.x * lateral + tangent.y * along;
  out.s = s;
}

/**
 * Draws ONE frame of the trail at progress `t` (0..1) onto `ctx`, in CSS pixels (the caller has
 * already applied the device-pixel-ratio transform). A pure function of `(scene, t)`.
 */
export function drawTrailFrame(
  ctx: CanvasRenderingContext2D,
  scene: TrailScene,
  width: number,
  height: number,
  t: number,
): void {
  ctx.clearRect(0, 0, width, height);
  if (t < 0.09 || t > 1) return;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const { path, unit } = scene;
  const fade = 1 - smooth(0.9, 0.98, t);

  // Ribbon: a head and a tail travelling the same curve, three stroke passes (glow, body, core).
  const head = easeInOut(clamp01((t - 0.16) / 0.5));
  const tail = easeInOut(clamp01((t - 0.3) / 0.5));
  const envelope = smooth(0.12, 0.2, t) * fade;
  if (head > 0.001 && envelope > 0) {
    const segments = 28;
    for (let k = 0; k < segments; k += 1) {
      const f = (k + 1) / segments;
      const s0 = tail + (head - tail) * (k / segments);
      const s1 = tail + (head - tail) * f;
      const a = path.at(s0);
      const b = path.at(s1);
      const base =
        3 * unit +
        24 * unit * (1 - smooth(0, 0.3, s1)) +
        9 * unit * smooth(0.75, 1, s1) * (1 - smooth(0.97, 1, s1));
      const w = base * (0.2 + 0.8 * Math.pow(f, 1.3));
      const e = envelope * Math.pow(f, 1.5);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = RIBBON_FAR;
      ctx.globalAlpha = 0.09 * e;
      ctx.lineWidth = w * 4.2;
      ctx.stroke();
      ctx.strokeStyle = RIBBON_MID;
      ctx.globalAlpha = 0.3 * e;
      ctx.lineWidth = w * 1.5;
      ctx.stroke();
      ctx.strokeStyle = RIBBON_CORE;
      ctx.globalAlpha = 0.85 * e;
      ctx.lineWidth = Math.max(1, w * 0.4);
      ctx.stroke();
    }
    // A soft glow at the head of the ribbon.
    const tip = path.at(head);
    const glow = smooth(0.14, 0.24, t) * (1 - smooth(0.66, 0.78, t));
    if (glow > 0) {
      const radius = 52 * unit;
      const gradient = ctx.createRadialGradient(tip.x, tip.y, 0, tip.x, tip.y, radius);
      gradient.addColorStop(0, "rgba(120,190,255,.75)");
      gradient.addColorStop(0.25, "rgba(60,110,255,.35)");
      gradient.addColorStop(1, "rgba(90,80,255,0)");
      ctx.globalAlpha = glow;
      ctx.fillStyle = gradient;
      ctx.fillRect(tip.x - radius, tip.y - radius, radius * 2, radius * 2);
    }
  }

  // A few thin streaks of energy alongside the ribbon.
  for (const line of scene.lines) {
    const lead = easeInOut(clamp01((t - 0.16 - line.lag) / 0.5));
    const strength = smooth(0, 0.1, lead) * (1 - smooth(0.85, 1, lead)) * fade;
    if (strength <= 0.01) continue;
    let previous: Point | null = null;
    for (let k = 0; k <= 7; k += 1) {
      const s = easeInOut(clamp01((t - (k / 7) * line.len - 0.16 - line.lag) / 0.5));
      const centre = path.at(s);
      const tangent = path.tangent(s);
      const offset = line.o * Math.sin(Math.PI * s) * smooth(0, 0.25, s);
      const point = { x: centre.x - tangent.y * offset, y: centre.y + tangent.x * offset };
      if (previous !== null) {
        ctx.beginPath();
        ctx.moveTo(previous.x, previous.y);
        ctx.lineTo(point.x, point.y);
        ctx.strokeStyle = line.col;
        ctx.globalAlpha = line.a * strength * Math.pow(1 - k / 8, 1.4);
        ctx.lineWidth = line.w;
        ctx.stroke();
      }
      previous = point;
    }
  }

  // Particles: short motion-blurred dashes (current position back to ~16 ms ago).
  const now: Placed = { x: 0, y: 0, s: 0 };
  const before: Placed = { x: 0, y: 0, s: 0 };
  for (const particle of scene.particles) {
    if (t < particle.r - 0.005) continue;
    place(particle, scene, t, now);
    place(particle, scene, t - 0.016, before);
    const alpha =
      particle.a0 *
      smooth(particle.r - 0.005, particle.r + 0.02, t) *
      fade *
      (0.78 + 0.22 * Math.sin(t * 38 + particle.ph));
    if (alpha < 0.02) continue;
    const radius = particle.sz * (1 - 0.3 * smooth(0.72, 1, now.s));
    ctx.strokeStyle = particle.col;
    ctx.beginPath();
    ctx.moveTo(before.x, before.y);
    ctx.lineTo(now.x + 0.01, now.y);
    if (particle.bright) {
      ctx.globalAlpha = alpha * 0.18;
      ctx.lineWidth = radius * 6;
      ctx.stroke();
    }
    ctx.globalAlpha = alpha;
    ctx.lineWidth = radius * 2;
    ctx.stroke();
  }

  // Landing bloom where the small logo appears.
  const bloom = smooth(0.76, 0.9, t) * (1 - smooth(0.9, 0.99, t));
  if (bloom > 0) {
    const radius = 60 * unit;
    const gradient = ctx.createRadialGradient(scene.end.x, scene.end.y, 0, scene.end.x, scene.end.y, radius);
    gradient.addColorStop(0, "rgba(80,140,255,.4)");
    gradient.addColorStop(1, "rgba(120,100,255,0)");
    ctx.globalAlpha = bloom;
    ctx.fillStyle = gradient;
    ctx.fillRect(scene.end.x - radius, scene.end.y - radius, radius * 2, radius * 2);
  }
  ctx.globalAlpha = 1;
}

export interface LogoTrailOptions {
  canvas: HTMLCanvasElement;
  scene: TrailScene;
  /** CSS size of the canvas. */
  width: number;
  height: number;
  /** Device pixel ratio, already capped by the caller. */
  dpr: number;
  durationMs?: number;
  /** Fired every frame with the progress 0..1 (the caller fades the hero logo with it). */
  onProgress?: (t: number) => void;
  /** Fired ONCE, the first frame at or after `TRAIL_ARRIVE_AT` (the small logo may appear). */
  onArrive?: () => void;
  /** Fired ONCE when the trail has fully played (never after `cancel`). */
  onDone?: () => void;
  /** Injectable for tests. */
  now?: () => number;
  requestFrame?: (callback: () => void) => number;
  cancelFrame?: (id: number) => void;
}

/**
 * Starts the trail and returns its `cancel` function - or `null` if the canvas has no 2D context
 * (the caller falls back to a plain fade). Exactly one `requestAnimationFrame` chain exists per
 * call; `cancel` stops it for good (no callback fires afterwards) and clears the canvas.
 */
export function startLogoTrail(options: LogoTrailOptions): (() => void) | null {
  const { canvas, scene, width, height, dpr } = options;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const duration = options.durationMs ?? TRAIL_DURATION_MS;
  const now = options.now ?? (() => performance.now());
  const requestFrame =
    options.requestFrame ?? ((callback: () => void) => window.requestAnimationFrame(callback));
  const cancelFrame = options.cancelFrame ?? ((id: number) => window.cancelAnimationFrame(id));

  canvas.width = Math.max(1, Math.round(width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const startedAt = now();
  let frameId = 0;
  let cancelled = false;
  let arrived = false;

  const frame = () => {
    if (cancelled) return;
    const t = clamp01((now() - startedAt) / duration);
    options.onProgress?.(t);
    if (!arrived && t >= TRAIL_ARRIVE_AT) {
      arrived = true;
      options.onArrive?.();
    }
    drawTrailFrame(ctx, scene, width, height, t);
    if (t < 1) {
      frameId = requestFrame(frame);
      return;
    }
    ctx.clearRect(0, 0, width, height);
    options.onDone?.();
  };
  frameId = requestFrame(frame);

  return () => {
    if (cancelled) return;
    cancelled = true;
    cancelFrame(frameId);
    ctx.clearRect(0, 0, width, height);
  };
}
