"use client";

import { useEffect } from "react";

import { allAccessibleProperties, resolveSelectedProperty } from "@/lib/session/properties";
import { useSession } from "@/lib/session/session-context";

import { AppShell } from "./app-shell";
import { AuthGate } from "./auth-gate";
import { DecisionDetailView } from "./decision-detail-view";

export interface DecisionDetailScreenProps {
  decisionId: string;
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  /**
   * Called whenever the property in scope needs to change: the URL's property was invalid/
   * foreign/missing (client-side rejected, never trusted enough to call the API with), OR the
   * user picked a different property from the shell's own selector while already on this page.
   * EITHER way, this component never tries to reuse the current `decisionId` under a different
   * property - the caller always navigates to `/oggi` for the given property id instead.
   */
  onNavigateToOggi: (propertyId: string | null) => void;
  onNavigateToLogin: () => void;
}

function DecisionDetailScreenContent({
  decisionId,
  requestedPropertyId,
  onNavigateToOggi,
  onNavigateToLogin,
}: DecisionDetailScreenProps) {
  const { session } = useSession();
  const properties = session ? allAccessibleProperties(session) : [];
  const selected = session ? resolveSelectedProperty(session, requestedPropertyId) : null;
  const needsRedirect = selected === null || selected.id !== requestedPropertyId;

  useEffect(() => {
    if (needsRedirect) {
      onNavigateToOggi(selected?.id ?? null);
    }
  }, [needsRedirect, selected, onNavigateToOggi]);

  if (!session) {
    // AuthGate only ever mounts this once status === "authenticated"; TypeScript still needs
    // the narrowing.
    return null;
  }

  if (needsRedirect) {
    // Bouncing to /oggi via the effect above - never render the decision itself for a property
    // the URL did not genuinely, exactly ask for.
    return <div className="decision-detail__redirecting" aria-live="polite" aria-busy="true" />;
  }

  return (
    <AppShell
      properties={properties}
      selectedPropertyId={selected.id}
      onSelectProperty={onNavigateToOggi}
      onLoggedOut={onNavigateToLogin}
    >
      <DecisionDetailView propertyId={selected.id} decisionId={decisionId} />
    </AppShell>
  );
}

/** The full Decision Detail screen (Gate 15): auth bootstrap gate, property validation, the
 * authenticated shell, and the decision itself. Framework-free - `app/oggi/decisioni/
 * [decisionId]/page.tsx` wires this to the real router. */
export function DecisionDetailScreen(props: DecisionDetailScreenProps) {
  return (
    <AuthGate onUnauthenticated={props.onNavigateToLogin}>
      <DecisionDetailScreenContent {...props} />
    </AuthGate>
  );
}
