import { describe, expect, it } from "vitest";

import type { PropertyAccess } from "@ninfa/contracts";

import { demoStructureOverview } from "./demo-structure";
import { formatUpdateAge } from "./format";
import { getStructureOverview, notConfiguredSources } from "./overview";
import type { DataSource } from "./types";

const NOW = new Date("2026-10-23T10:00:00Z");

const property: PropertyAccess = {
  id: "p1",
  name: "Residenza Alba",
  slug: "residenza-alba",
  timezone: "America/New_York",
};

describe("getStructureOverview (what the real route shows)", () => {
  it("knows the property's name and timezone, and nothing else", () => {
    const { profile } = getStructureOverview(property);

    expect(profile.name).toBe("Residenza Alba");
    expect(profile.timeZone).toBe("America/New_York");
    expect(profile).toEqual({
      name: "Residenza Alba",
      type: null,
      stars: null,
      location: null,
      roomCount: null,
      timeZone: "America/New_York",
      currency: null,
      mainSeason: null,
      imageSrc: null,
    });
  });

  it("has no room type, no parameter and no connected source: all of it is not configured", () => {
    const overview = getStructureOverview(property);

    expect(overview.rooms).toEqual([]);
    expect(overview.parameters).toEqual({ opening: null, peakSeason: null, maxGuests: null });
    expect(overview.sources.map((source) => source.category)).toEqual([
      "PMS",
      "CHANNEL_MANAGER",
      "OTA",
      "ACCOUNTING",
      "STAFF",
    ]);
    for (const source of overview.sources) {
      expect(source.connection).toEqual({ status: "NOT_CONNECTED" });
    }
    expect(overview.sources).toEqual(notConfiguredSources());
  });

  it("carries no value of the demo dataset anywhere, whoever the property is", () => {
    const demo = demoStructureOverview(NOW);
    const real = JSON.stringify(getStructureOverview(property));

    for (const value of [
      demo.profile.name,
      demo.profile.type,
      demo.profile.location,
      demo.profile.imageSrc,
      ...demo.rooms.flatMap((room) => [room.name, room.code]),
      "Mews",
      "SiteMinder",
      "Booking.com",
      "TeamSystem",
    ]) {
      expect(real).not.toContain(String(value));
    }
  });
});

describe("demoStructureOverview (explicit fixture: development and tests only)", () => {
  it("is the complete example of the approved reference", () => {
    const demo = demoStructureOverview(NOW);

    expect(demo.profile).toMatchObject({
      name: "Villa Serenità",
      type: "Hotel",
      stars: 4,
      location: "Bellagio (CO), Italia",
      roomCount: 32,
      timeZone: "Europe/Rome",
      currency: "EUR",
    });
    expect(demo.rooms.map((room) => room.name)).toEqual(["Classic", "Deluxe", "Junior Suite", "Suite"]);
    expect(demo.parameters.peakSeason).toEqual({ fromMonth: 6, toMonth: 9 });
  });

  it("keeps the capacity equal to the room types' theoretical capacity, and the room count equal to the inventory", () => {
    const { rooms, parameters, profile } = demoStructureOverview(NOW);
    const theoreticalGuests = rooms.reduce((sum, room) => sum + room.rooms * (room.maxAdults + room.maxChildren), 0);
    const roomCount = rooms.reduce((sum, room) => sum + room.rooms, 0);

    expect(parameters.maxGuests).toBe(92);
    expect(parameters.maxGuests).toBe(theoreticalGuests);
    expect(profile.roomCount).toBe(roomCount);
  });

  it("has connected systems whose last update is anchored to the given instant", () => {
    const connected = demoStructureOverview(NOW).sources.flatMap((source) =>
      source.connection.status === "CONNECTED"
        ? [[source.connection.provider, formatUpdateAge(source.connection.lastUpdateAt, NOW)]]
        : [],
    );

    expect(connected).toEqual([
      ["Mews", "4 min fa"],
      ["SiteMinder", "6 min fa"],
      ["Booking.com", "7 min fa"],
    ]);
  });

  it("names no system on a source that is not connected, whatever its category", () => {
    for (const source of demoStructureOverview(NOW).sources) {
      if (source.connection.status === "NOT_CONNECTED") {
        expect(Object.keys(source.connection)).toEqual(["status"]);
      }
    }
  });
});

describe("DataSource type", () => {
  it("does not let a source that is not connected carry a provider", () => {
    const wired: DataSource = {
      category: "OTA",
      connection: { status: "CONNECTED", provider: "Any OTA", lastUpdateAt: NOW.toISOString() },
    };
    const notWired: DataSource = {
      category: "ACCOUNTING",
      // @ts-expect-error a not-connected source has no `provider`: this is what keeps a vendor off its card
      connection: { status: "NOT_CONNECTED", provider: "Any vendor" },
    };

    expect(wired.connection.status).toBe("CONNECTED");
    expect(notWired.category).toBe("ACCOUNTING");
  });
});
