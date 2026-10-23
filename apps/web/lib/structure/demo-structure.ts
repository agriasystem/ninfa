import type { StructureOverview } from "./types";

/**
 * DEMO DATA for the Struttura page - an explicit, COMPLETE fixture for development and tests. NINFA has no
 * endpoint for the structure yet; the values are the ones of the approved visual reference, so the screen can
 * be reviewed against it: Villa Serenità, Hotel, 4 stelle, Bellagio (CO), 32 camere in four room types, the
 * three operating parameters and three connected systems.
 *
 * They are NOT facts about any real property, and the real route NEVER uses them: `getStructureOverview`
 * (lib/structure/overview.ts) reports everything it has no real data for as not configured. This file is
 * imported only by tests and by whoever wants to look at the full page - by passing
 * `getOverview={(_property, now) => demoStructureOverview(now)}` to `StrutturaScreen`, which the route itself
 * never does. A demo vendor shown as "Collegato", or a demo room type shown as the inventory, on a real
 * property could be taken for operating data.
 */

/** The placeholder photo, served from `public/placeholders` (a crop of the approved reference). */
export const DEMO_STRUCTURE_PHOTO = "/placeholders/struttura-placeholder.jpg";

const MINUTE = 60_000;

/** `now` anchors the connected systems' "last update" instants, so the demo always reads a few minutes old. */
export function demoStructureOverview(now: Date): StructureOverview {
  const minutesAgo = (minutes: number) => new Date(now.getTime() - minutes * MINUTE).toISOString();

  return {
    profile: {
      name: "Villa Serenità",
      type: "Hotel",
      stars: 4,
      location: "Bellagio (CO), Italia",
      roomCount: 32,
      timeZone: "Europe/Rome",
      currency: "EUR",
      mainSeason: { fromMonth: 3, toMonth: 11 },
      imageSrc: DEMO_STRUCTURE_PHOTO,
    },
    rooms: [
      { id: "classic", name: "Classic", code: "CLS", rooms: 8, maxAdults: 2, maxChildren: 0, status: "ACTIVE" },
      { id: "deluxe", name: "Deluxe", code: "DLX", rooms: 12, maxAdults: 2, maxChildren: 1, status: "ACTIVE" },
      { id: "junior-suite", name: "Junior Suite", code: "JSU", rooms: 8, maxAdults: 3, maxChildren: 0, status: "ACTIVE" },
      { id: "suite", name: "Suite", code: "STE", rooms: 4, maxAdults: 4, maxChildren: 0, status: "ACTIVE" },
    ],
    parameters: {
      opening: { allYear: true, annualClosure: null },
      peakSeason: { fromMonth: 6, toMonth: 9 },
      // the theoretical capacity of the room types above (8x2 + 12x3 + 8x3 + 4x4); a test keeps them equal
      maxGuests: 92,
    },
    sources: [
      { category: "PMS", connection: { status: "CONNECTED", provider: "Mews", lastUpdateAt: minutesAgo(4) } },
      { category: "CHANNEL_MANAGER", connection: { status: "CONNECTED", provider: "SiteMinder", lastUpdateAt: minutesAgo(6) } },
      { category: "OTA", connection: { status: "CONNECTED", provider: "Booking.com", lastUpdateAt: minutesAgo(7) } },
      { category: "ACCOUNTING", connection: { status: "NOT_CONNECTED" } },
      { category: "STAFF", connection: { status: "NOT_CONNECTED" } },
    ],
  };
}
