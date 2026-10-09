"use client";

import { createContext, useContext, type RefObject } from "react";

/**
 * The app shell owns the small logo that lives at the top of the sidebar (Home UI V1). The Home's
 * hero owns the BIG one. While the hero logo is on screen the sidebar slot stays empty (hidden,
 * but its box is kept - it is where the logo transition lands); once the logo has travelled there,
 * the Home reveals it. Every other page simply shows the small logo from the start.
 */
export interface ShellLogoControl {
  /** The sidebar logo's own box - the landing target of the logo transition. */
  slotRef: RefObject<HTMLElement | null>;
  /** `true` hides the small logo (the Home's hero logo is showing); `false` reveals it. */
  setHidden: (hidden: boolean) => void;
}

export const ShellLogoContext = createContext<ShellLogoControl | null>(null);

export function useShellLogo(): ShellLogoControl {
  const control = useContext(ShellLogoContext);
  if (!control) {
    throw new Error("useShellLogo must be used within an AppShell");
  }
  return control;
}
