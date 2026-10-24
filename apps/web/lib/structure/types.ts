/**
 * What the Struttura page shows, as ONE object (`StructureOverview`). Every field is a plain fact in the
 * form a backend would send it - an IANA zone, an ISO currency code, month numbers, a timestamp - and
 * never a display string: the wording ("Europe/Rome (CET)", "Marzo – Novembre", "4 min fa") is built in
 * `lib/structure/format.ts` and `lib/structure/copy.ts`.
 *
 * NOT CONFIGURED is a first-class state: a field that nothing has set is `null` (a list: empty), and the page
 * then says so ("Non configurata") instead of showing a value. Nothing is ever filled in on a whim.
 *
 * Today the only producer is `getStructureOverview` (`lib/structure/overview.ts`). It fills what the session
 * really knows (the name and the timezone) and leaves everything else not configured: no profile fact, no room
 * type, no parameter. (The data sources of "Fonti dati" are NOT part of this object: they come from their own
 * backend API, `lib/api/data-sources.ts`.) When a Struttura endpoint exists, replacing that one function is the
 * whole job - no component reads anything but this shape. The complete example dataset
 * (`demoStructureOverview`, `lib/structure/demo-structure.ts`) is an explicit fixture for development and tests;
 * the real route never uses it.
 *
 * The page describes the structure NINFA needs to read the data correctly. It is not a PMS: nothing here
 * carries a booking, a rate, a calendar or a room assignment.
 */

/** A run of calendar months, 1 = January ... 12 = December. `from` > `to` wraps over the year end. */
export interface MonthRange {
  fromMonth: number;
  toMonth: number;
}

export interface StructureProfile {
  /** The property's own name (from the session): always known. */
  name: string;
  /** "Hotel", "Agriturismo", ... as the structure is classified. `null` = not configured. */
  type: string | null;
  /** 1-5. `null` = not configured. */
  stars: number | null;
  location: string | null;
  roomCount: number | null;
  /** IANA zone, e.g. "Europe/Rome" (from the session): always known. */
  timeZone: string;
  /** ISO 4217, e.g. "EUR". `null` = not configured. */
  currency: string | null;
  mainSeason: MonthRange | null;
  /** `null` until the structure has a photo: the page then shows a neutral tile. */
  imageSrc: string | null;
}

export type RoomTypeStatus = "ACTIVE" | "INACTIVE";

export interface RoomType {
  id: string;
  name: string;
  code: string;
  rooms: number;
  maxAdults: number;
  maxChildren: number;
  status: RoomTypeStatus;
}

/** Every parameter is `null` until it is configured. */
export interface OperatingParameters {
  opening: {
    allYear: boolean;
    /** The yearly closure, `null` when there is none. */
    annualClosure: MonthRange | null;
  } | null;
  peakSeason: MonthRange | null;
  /** The most guests the structure can host at once. */
  maxGuests: number | null;
}

export interface StructureOverview {
  profile: StructureProfile;
  /** Empty = the inventory is not configured. */
  rooms: RoomType[];
  parameters: OperatingParameters;
}
