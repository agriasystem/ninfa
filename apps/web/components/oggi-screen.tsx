"use client";

import { useEffect } from "react";

import { copy } from "@/lib/copy";
import { allAccessibleProperties, resolveSelectedProperty } from "@/lib/session/properties";
import { useSession } from "@/lib/session/session-context";

import { AppShell } from "./app-shell";
import { AuthGate } from "./auth-gate";
import { TodayScreen } from "./today-screen";

export interface OggiScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  /** Called whenever the resolved property differs from what the URL asked for: a real
   * selection, or a correction of an unknown/foreign id back to a real one. The caller updates
   * the URL/query - this component never trusts an arbitrary id enough to call the API with it. */
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
}

function OggiContent({ requestedPropertyId, onSelectProperty, onNavigateToLogin }: OggiScreenProps) {
  const { session, refresh } = useSession();
  const properties = session ? allAccessibleProperties(session) : [];
  const selected = session ? resolveSelectedProperty(session, requestedPropertyId) : null;

  useEffect(() => {
    if (selected && requestedPropertyId !== selected.id) {
      onSelectProperty(selected.id);
    }
  }, [selected, requestedPropertyId, onSelectProperty]);

  if (!session) {
    // AuthGate only ever mounts this once status === "authenticated"; TypeScript still needs
    // the narrowing.
    return null;
  }

  if (selected === null) {
    return (
      <AppShell
        properties={[]}
        selectedPropertyId=""
        onSelectProperty={onSelectProperty}
        onLoggedOut={onNavigateToLogin}
      >
        <div className="property-empty-state">
          <h1>{copy.property.emptyStateTitle}</h1>
          <p>{copy.property.emptyStateBody}</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      properties={properties}
      selectedPropertyId={selected.id}
      onSelectProperty={onSelectProperty}
      onLoggedOut={onNavigateToLogin}
    >
      <TodayScreen
        propertyId={selected.id}
        timeZone={selected.timezone}
        onPropertyInvalid={() => void refresh()}
      />
    </AppShell>
  );
}

/** The full "/oggi" screen: auth bootstrap gate, property resolution, the authenticated shell,
 * and the feed itself. Framework-free (no `next/navigation` import) - `app/oggi/page.tsx` wires
 * this to the real router; this is what actually gets tested. */
export function OggiScreen(props: OggiScreenProps) {
  return (
    <AuthGate onUnauthenticated={props.onNavigateToLogin}>
      <OggiContent {...props} />
    </AuthGate>
  );
}
