"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { heroOpacityAt } from "@/lib/motion/logo-trail";
import { isSmallViewport, prefersReducedMotion } from "@/lib/motion/prefers";

/** `idle`: the hero logo is on screen. `morphing`: it is on its way. `settled`: it has landed in
 * the sidebar and the hero logo is gone for good (no reverse animation in V1). */
export type LogoPhase = "idle" | "morphing" | "settled";
/** `trail`: the canvas ribbon. `fade`: a plain ~150 ms cross-fade (reduced motion excluded - that
 * one swaps immediately, no animation at all). */
export type LogoMode = "trail" | "fade";

export const FADE_MS = 150;

export interface LogoTransitionHandle {
  phase: LogoPhase;
  mode: LogoMode | null;
  /** The hero `<img>`: measured and sampled by the trail, faded by it. */
  heroRef: RefObject<HTMLImageElement | null>;
  /** Idempotent: only the FIRST call ever starts the (single) transition. */
  trigger: () => void;
  /** The callbacks the trail canvas reports through. */
  trail: {
    onProgress: (t: number) => void;
    onArrive: () => void;
    onDone: () => void;
    /** The canvas cannot run (no 2D context, logo not decoded, no geometry): degrade to a fade. */
    onUnavailable: () => void;
  };
}

export interface UseLogoTransitionOptions {
  /** Reveals the small logo in the sidebar slot. */
  revealSidebarLogo: () => void;
}

/**
 * The state machine behind the Home's logo transition (Home UI V1): `idle -> morphing -> settled`.
 * It is started by `trigger()` - which the Mia input calls on the FIRST real (non-whitespace)
 * character typed or pasted, never on focus - and runs EXACTLY once per mount, whatever the user
 * does next (clearing the input never reverses it).
 *
 * Which visual runs is decided here, once, at trigger time:
 * - `prefers-reduced-motion`: no canvas, no animation - an immediate swap;
 * - a small viewport, or a canvas that turns out to be unavailable: a ~150 ms fade;
 * - otherwise: the canvas trail (`LogoTrailCanvas`), ~1 s.
 */
export function useLogoTransition({
  revealSidebarLogo,
}: UseLogoTransitionOptions): LogoTransitionHandle {
  const [phase, setPhase] = useState<LogoPhase>("idle");
  const [mode, setMode] = useState<LogoMode | null>(null);
  const heroRef = useRef<HTMLImageElement | null>(null);
  const startedRef = useRef(false);
  const fadeTimerRef = useRef<number | undefined>(undefined);
  const revealRef = useRef(revealSidebarLogo);

  useEffect(() => {
    revealRef.current = revealSidebarLogo;
  });

  useEffect(
    () => () => {
      window.clearTimeout(fadeTimerRef.current);
    },
    [],
  );

  const settle = useCallback(() => {
    setPhase("settled");
    revealRef.current();
  }, []);

  const startFade = useCallback(() => {
    setMode("fade");
    setPhase("morphing");
    window.clearTimeout(fadeTimerRef.current);
    fadeTimerRef.current = window.setTimeout(settle, FADE_MS);
  }, [settle]);

  const trigger = useCallback(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    if (prefersReducedMotion()) {
      setMode("fade");
      settle();
      return;
    }
    if (isSmallViewport()) {
      startFade();
      return;
    }
    setMode("trail");
    setPhase("morphing");
  }, [settle, startFade]);

  const onProgress = useCallback((t: number) => {
    const hero = heroRef.current;
    if (hero) hero.style.opacity = String(heroOpacityAt(t));
  }, []);

  const onArrive = useCallback(() => {
    revealRef.current();
  }, []);

  const onDone = settle;

  const onUnavailable = useCallback(() => {
    // Only a trail that never started can degrade; one that already finished stays finished.
    if (!startedRef.current) return;
    startFade();
  }, [startFade]);

  return {
    phase,
    mode,
    heroRef,
    trigger,
    trail: { onProgress, onArrive, onDone, onUnavailable },
  };
}
