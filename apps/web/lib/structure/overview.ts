import type { PropertyAccess } from "@ninfa/contracts";

import { DATA_SOURCE_CATEGORIES, type DataSource, type StructureOverview } from "./types";

/** Every category, none connected: what the page says while nothing real states a connection. */
export function notConfiguredSources(): DataSource[] {
  return DATA_SOURCE_CATEGORIES.map((category) => ({ category, connection: { status: "NOT_CONNECTED" } }));
}

/**
 * The Struttura page's data for ONE property. Only what NINFA really knows is filled in: the property's name
 * and timezone, which come from the session (so the page never contradicts the name shown in the header).
 * Everything else - the profile facts, the room types, the operating parameters, the connected systems - is NOT
 * CONFIGURED, because no real data says otherwise; the page shows exactly that ("Non configurata", an empty
 * inventory, "Nessuna fonte collegata"). This function never reads the demo dataset: a demo hotel, inventory
 * or vendor on a real property could be mistaken for operating data.
 *
 * This is the single seam to replace with an API call.
 */
export function getStructureOverview(property: PropertyAccess): StructureOverview {
  return {
    profile: {
      name: property.name,
      type: null,
      stars: null,
      location: null,
      roomCount: null,
      timeZone: property.timezone,
      currency: null,
      mainSeason: null,
      imageSrc: null,
    },
    rooms: [],
    parameters: { opening: null, peakSeason: null, maxGuests: null },
    sources: notConfiguredSources(),
  };
}
