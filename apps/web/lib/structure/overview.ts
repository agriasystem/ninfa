import type { PropertyAccess } from "@ninfa/contracts";

import type { StructureOverview } from "./types";

/**
 * The Struttura page's data for ONE property. Only what NINFA really knows is filled in: the property's name
 * and timezone, which come from the session (so the page never contradicts the name shown in the header).
 * Everything else - the profile facts, the room types, the operating parameters - is NOT CONFIGURED, because
 * no real data says otherwise; the page shows exactly that ("Non configurata", an empty inventory). This
 * function never reads the demo dataset: a demo hotel or inventory on a real property could be mistaken for
 * operating data. (The data sources are read from their own API, not from here.)
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
  };
}
