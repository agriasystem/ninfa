"use client";

import { HomeScreen } from "./home-screen";
import { PropertyScreen } from "./property-screen";

export interface OggiScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  /** Called whenever the resolved property differs from what the URL asked for: a real
   * selection, or a correction of an unknown/foreign id back to a real one. The caller updates
   * the URL/query - this component never trusts an arbitrary id enough to call the API with it. */
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
}

/** The full "/oggi" screen (Home UI V1): auth bootstrap gate, property resolution, the sidebar shell
 * and the decision-first Home itself. Framework-free (no `next/navigation` import) -
 * `app/oggi/page.tsx` wires this to the real router; this is what actually gets tested. */
export function OggiScreen(props: OggiScreenProps) {
  return (
    <PropertyScreen {...props} activeSection="oggi" variant="home" logoInitiallyHidden>
      {(selected, onPropertyInvalid) => (
        <HomeScreen
          propertyId={selected.id}
          timeZone={selected.timezone}
          onPropertyInvalid={onPropertyInvalid}
        />
      )}
    </PropertyScreen>
  );
}
