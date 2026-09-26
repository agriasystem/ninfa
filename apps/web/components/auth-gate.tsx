"use client";

import { useEffect, type ReactNode } from "react";

import { useSession } from "@/lib/session/session-context";

export interface AuthGateProps {
  children: ReactNode;
  onUnauthenticated: () => void;
}

/**
 * Never shows authenticated content for a single instant before knowing whether a real session
 * exists (Gate 14 spec, "Auth bootstrap"): renders a neutral, shell-only loading state while
 * `status === "loading"`, and defers to `onUnauthenticated` (the caller redirects to /login)
 * once the bootstrap call comes back as `unauthenticated` - never during render itself.
 */
export function AuthGate({ children, onUnauthenticated }: AuthGateProps) {
  const { status } = useSession();

  useEffect(() => {
    if (status === "unauthenticated") {
      onUnauthenticated();
    }
  }, [status, onUnauthenticated]);

  if (status === "authenticated") {
    return <>{children}</>;
  }

  return <div className="auth-gate__loading" aria-live="polite" aria-busy="true" />;
}
