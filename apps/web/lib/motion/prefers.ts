/**
 * Environment checks for the Home's logo transition (Home UI V1). Both are SAFE outside a browser
 * and inside jsdom (which defines no `matchMedia`): a missing API reads as "no preference" - the
 * caller then decides from what it can actually do (e.g. no 2D canvas context -> a plain fade).
 */

/** Below this viewport width the transition is a simple fade, never the canvas trail (the trail
 * is a desktop/laptop flourish; on a phone the sidebar logo is a different, tiny target). */
export const TRAIL_MIN_VIEWPORT_WIDTH = 768;

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function isSmallViewport(): boolean {
  return typeof window !== "undefined" && window.innerWidth < TRAIL_MIN_VIEWPORT_WIDTH;
}
