"use client";

import { useEffect, useRef, type RefObject } from "react";

import {
  buildEnergyLines,
  buildParticles,
  createTrailPath,
  sampleLogoPixels,
  seededRandom,
  startLogoTrail,
  type Box,
} from "@/lib/motion/logo-trail";

/** Plenty for a dense, fluid trail on a ~110 px logo - and cheap enough for a 1 s burst. */
export const TRAIL_PARTICLE_COUNT = 450;
/** The canvas extends this far beyond the two logo boxes so the arc and the glow are never cut. */
const MARGIN = 140;
const MAX_DPR = 2;

export interface LogoTrailCanvasProps {
  heroRef: RefObject<HTMLImageElement | null>;
  slotRef: RefObject<HTMLElement | null>;
  onProgress: (t: number) => void;
  onArrive: () => void;
  onDone: () => void;
  onUnavailable: () => void;
}

/**
 * The TEMPORARY canvas overlay of the logo transition (Home UI V1). It exists in the DOM only while
 * the trail plays (the parent mounts it for the `morphing` phase and unmounts it afterwards):
 * `position: fixed`, `pointer-events: none`, `aria-hidden` - it is decoration and must never take a
 * click or be announced.
 *
 * Geometry is REAL: the hero logo's and the sidebar slot's own `getBoundingClientRect()` at the
 * moment the effect runs (no prototype coordinates). The particles are sampled from the hero logo's
 * own pixels. Everything is torn down in the effect's cleanup (`cancelAnimationFrame`), so unmounting
 * mid-flight - or React StrictMode's mount/unmount/mount - never leaves a loop running or fires a
 * stale callback. Anything that stops the trail from starting reports `onUnavailable` instead.
 */
export function LogoTrailCanvas(props: LogoTrailCanvasProps) {
  const { heroRef, slotRef } = props;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const callbacks = useRef(props);

  useEffect(() => {
    callbacks.current = props;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    const hero = heroRef.current;
    const slot = slotRef.current;
    if (!canvas || !hero || !slot) {
      callbacks.current.onUnavailable();
      return undefined;
    }
    const heroRect = hero.getBoundingClientRect();
    const slotRect = slot.getBoundingClientRect();
    if (
      heroRect.width === 0 ||
      heroRect.height === 0 ||
      slotRect.width === 0 ||
      slotRect.height === 0
    ) {
      callbacks.current.onUnavailable();
      return undefined;
    }

    const left = Math.max(0, Math.min(heroRect.left, slotRect.left) - MARGIN);
    const top = Math.max(0, Math.min(heroRect.top, slotRect.top) - MARGIN);
    const right = Math.max(heroRect.right, slotRect.right) + MARGIN;
    const bottom = Math.max(heroRect.bottom, slotRect.bottom) + MARGIN;
    const width = right - left;
    const height = bottom - top;
    const toLocal = (rect: DOMRect): Box => ({
      x: rect.left - left,
      y: rect.top - top,
      width: rect.width,
      height: rect.height,
    });
    const heroBox = toLocal(heroRect);
    const slotBox = toLocal(slotRect);

    const random = seededRandom(11);
    const samples = sampleLogoPixels(hero, TRAIL_PARTICLE_COUNT, random);
    if (samples === null) {
      callbacks.current.onUnavailable();
      return undefined;
    }
    const unit = heroBox.width / 78;
    const start = { x: heroBox.x + heroBox.width / 2, y: heroBox.y + heroBox.height / 2 };
    const end = { x: slotBox.x + slotBox.width / 2, y: slotBox.y + slotBox.height / 2 };

    canvas.style.left = `${left}px`;
    canvas.style.top = `${top}px`;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const cancel = startLogoTrail({
      canvas,
      width,
      height,
      dpr: Math.min(MAX_DPR, window.devicePixelRatio || 1),
      scene: {
        particles: buildParticles(samples, heroBox, random),
        path: createTrailPath(start, end),
        endScale: slotBox.height / heroBox.height,
        end,
        unit,
        lines: buildEnergyLines(random, unit),
      },
      onProgress: (t) => callbacks.current.onProgress(t),
      onArrive: () => callbacks.current.onArrive(),
      onDone: () => callbacks.current.onDone(),
    });
    if (cancel === null) {
      callbacks.current.onUnavailable();
      return undefined;
    }
    return cancel;
  }, [heroRef, slotRef]);

  return <canvas ref={canvasRef} className="logo-trail-canvas" aria-hidden="true" />;
}
