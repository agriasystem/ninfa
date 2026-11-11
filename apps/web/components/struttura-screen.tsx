"use client";

import { useEffect, useMemo } from "react";

import type { PropertyAccess } from "@ninfa/contracts";

import { STRUTTURA_INVENTORY_ANCHOR } from "@/lib/routes";
import { strutturaCopy } from "@/lib/structure/copy";
import { getStructureOverview } from "@/lib/structure/overview";
import type { StructureOverview } from "@/lib/structure/types";
import { useRoomInventory } from "@/lib/structure/use-room-inventory";

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
  onPropertyInvalid,
}: {
  property: PropertyAccess;
  actions: StrutturaActions;
  getOverview: StructureOverviewSource;
  onPropertyInvalid: () => void;
}) {
  const overview = useMemo(() => getOverview(property), [getOverview, property]);
  const { state: inventory, accept: acceptInventory } = useRoomInventory(property.id);
  // The profile's "Numero camere" and the inventory block say one number, the backend's.
  const roomCount =
    inventory.kind === "loaded" && inventory.inventory.configured
      ? inventory.inventory.rooms_available
      : overview.profile.roomCount;

  // A link to the inventory block ("Configura inventario" in Dati) lands before this content exists -
  // the session and the property resolve first - so neither the browser nor the router can scroll to
  // it: once the blocks are on screen, bring the one the address names into view.
  useEffect(() => {
    if (window.location.hash !== `#${STRUTTURA_INVENTORY_ANCHOR}`) return;
    document.getElementById(STRUTTURA_INVENTORY_ANCHOR)?.scrollIntoView?.({ block: "start" });
  }, []);

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
        <StrutturaProfile profile={{ ...overview.profile, roomCount }} />
        <StrutturaRooms
          propertyId={property.id}
          rooms={overview.rooms}
          inventory={inventory}
          actions={actions}
          onInventorySaved={acceptInventory}
        />
        <StrutturaParameters parameters={overview.parameters} actions={actions} />
        <StrutturaSources
          propertyId={property.id}
          timeZone={property.timezone}
          onPropertyInvalid={onPropertyInvalid}
        />
      </div>
    </div>
  );
}

export interface StrutturaScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
  /** What the profile and parameter buttons do. Not wired yet (see `StrutturaActions`). */
  actions?: StrutturaActions;
  /** Where the structure's data comes from: the one seam to point at a real endpoint. The route never passes
   * it, so a real property shows what is really known (its name and timezone) and "Non configurata" for the
   * rest. Development and tests pass `demoStructureOverview` to look at the complete example page. */
  getOverview?: StructureOverviewSource;
}

/** Builds the structure overview of a property (its profile, room inventory and parameters). */
export type StructureOverviewSource = (property: PropertyAccess) => StructureOverview;

const NO_ACTIONS: StrutturaActions = {};

/** The full "/struttura" screen: auth bootstrap gate, property resolution (0 / 1 / N properties), the
 * sidebar shell with "Struttura" active, and the page. Framework-free - `app/struttura/page.tsx` wires it
 * to the real router; this is what gets tested. No call to Mia or to a model; the only request is the
 * data-source API of "Fonti dati" (`lib/api/data-sources.ts`). */
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
      {(selected, onPropertyInvalid) => (
        <StrutturaContent
          property={selected}
          actions={actions}
          getOverview={getOverview}
          onPropertyInvalid={onPropertyInvalid}
        />
      )}
    </PropertyScreen>
  );
}
