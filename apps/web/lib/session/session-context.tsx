"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { SessionContextResponse } from "@ninfa/contracts";

import { getSession, logout as logoutRequest } from "@/lib/api/auth";

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export interface SessionState {
  status: SessionStatus;
  session: SessionContextResponse | null;
  /** Re-fetches GET /api/v1/auth/session (the auth bootstrap call) and updates status. */
  refresh: () => Promise<void>;
  /** Adopts the SessionContext returned directly by a successful login - never re-fetches it. */
  setSession: (session: SessionContextResponse) => void;
  /** Calls POST /api/v1/auth/logout, then clears local state regardless of the network result -
   * the HttpOnly cookie is cleared server-side either way; there is nothing sensitive left in
   * memory to protect by waiting on the response. */
  logout: () => Promise<void>;
}

const SessionReactContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [session, setSessionState] = useState<SessionContextResponse | null>(null);

  const refresh = useCallback(async () => {
    const result = await getSession();
    if (result.ok) {
      setSessionState(result.data);
      setStatus("authenticated");
    } else {
      setSessionState(null);
      setStatus("unauthenticated");
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    // The auth bootstrap call, inlined here (not `refresh()`) so the state updates happen only
    // after this specific effect run's own `await`, never synchronously inside the effect body,
    // and never for a stale run whose component already unmounted or re-ran.
    async function bootstrap() {
      const result = await getSession();
      if (ignore) return;
      if (result.ok) {
        setSessionState(result.data);
        setStatus("authenticated");
      } else {
        setSessionState(null);
        setStatus("unauthenticated");
      }
    }

    void bootstrap();
    return () => {
      ignore = true;
    };
    // Runs once on mount: the auth bootstrap call. Session changes afterwards happen through
    // setSession (login) or logout(), never a second automatic refetch.
  }, []);

  const setSession = useCallback((next: SessionContextResponse) => {
    setSessionState(next);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    await logoutRequest();
    setSessionState(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo<SessionState>(
    () => ({ status, session, refresh, setSession, logout }),
    [status, session, refresh, setSession, logout],
  );

  return <SessionReactContext.Provider value={value}>{children}</SessionReactContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionReactContext);
  if (!context) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
