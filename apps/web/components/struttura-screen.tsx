"use client";

import { useMemo, useState } from "react";

import type { PropertyAccess } from "@ninfa/contracts";

import { strutturaCopy } from "@/lib/structure/copy";
import { getStructureOverview } from "@/lib/structure/overview";
import type { StructureOverview } from "@/lib/structure/types";

import { EditStructureIcon } from "./icons";
import { PropertyScreen } from "./property-screen";
import { StrutturaParameters } from "./struttura-parameters";
import { StrutturaButton, type StrutturaActions } from "./struttura-parts";
import { StrutturaProfile } from "./struttura-profile";
import { StrutturaRooms } from "./struttura-rooms";
import { StrutturaSources } from "./struttura-sources";

/** The page of ONE property: its title with "Modifica struttura", then the four numbered blocks in the
 * approved order - profile, room inventory, operating parameters, data sources. */
function StrutturaContent({
  property,
  actions,
  getOverview,
}: {
  property: PropertyAccess;
  actions: StrutturaActions;
  getOverview: StructureOverviewSource;
}) {
  // One instant for the whole page: every "N min fa" is measured against the same `now`.
  const [now] = useState(() => new Date());
  const overview = useMemo(() => getOverview(property, now), [getOverview, property, now]);

  return (
    <div className="struttura-screen">
      <header className="struttura-screen__header">
        <div>
          <h1>{strutturaCopy.heading}</h1>
          <p className="struttura-screen__subtitle">{strutturaCopy.subtitle}</p>
        </div>
        <StrutturaButton variant="soft" Icon={EditStructureIcon} onClick={actions.onEditStructure}>
          {strutturaCopy.editStructure}
        </StrutturaButton>
      </header>

      <div className="struttura-screen__sections">
        <StrutturaProfile profile={overview.profile} />
        <StrutturaRooms rooms={overview.rooms} actions={actions} />
        <StrutturaParameters parameters={overview.parameters} actions={actions} />
        <StrutturaSources sources={overview.sources} now={now} actions={actions} />
      </div>
    </div>
  );
}

export interface StrutturaScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
  /** What the page's buttons do. None is wired yet (see `StrutturaActions`). */
  actions?: StrutturaActions;
  /** Where the structure's data comes from: the one seam to point at a real endpoint. The route never passes
   * it, so a real property shows what is really known (its name and timezone) and "Non configurata" for the
   * rest. Development and tests pass `demoStructureOverview` to look at the complete example page. */
  getOverview?: StructureOverviewSource;
}

/** Builds the overview of a property; `now` is the instant the page measures "N min fa" against. */
export type StructureOverviewSource = (property: PropertyAccess, now: Date) => StructureOverview;

const NO_ACTIONS: StrutturaActions = {};

/** The full "/struttura" screen: auth bootstrap gate, property resolution (0 / 1 / N properties), the
 * sidebar shell with "Struttura" active, and the page. Framework-free - `app/struttura/page.tsx` wires it
 * to the real router; this is what gets tested. Deterministic: no call to Mia, to a model or to the API. */
export function StrutturaScreen({
  requestedPropertyId,
  onSelectProperty,
  onNavigateToLogin,
  actions = NO_ACTIONS,
  getOverview = getStructureOverview,
}: StrutturaScreenProps) {
  return (
    <PropertyScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={onSelectProperty}
      onNavigateToLogin={onNavigateToLogin}
      activeSection="struttura"
      variant="wide"
    >
      {(selected) => <StrutturaContent property={selected} actions={actions} getOverview={getOverview} />}
    </PropertyScreen>
  );
}
