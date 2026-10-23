import { describe, expect, it } from "vitest";

import type { PropertyAccess } from "@ninfa/contracts";

import { demoStructureOverview } from "./demo-structure";
import { getStructureOverview } from "./overview";

const property: PropertyAccess = {
  id: "p1",
  name: "Residenza Alba",
  slug: "residenza-alba",
  timezone: "America/New_York",
};

describe("getStructureOverview (what the real route shows)", () => {
  it("knows the property's name and timezone, and nothing else", () => {
    const { profile } = getStructureOverview(property);

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

  it("has no room type and no parameter: all of it is not configured", () => {
    const overview = getStructureOverview(property);

    expect(overview.rooms).toEqual([]);
    expect(overview.parameters).toEqual({ opening: null, peakSeason: null, maxGuests: null });
  });

  it("carries no data source: those come from their own API, never from the structure model", () => {
    expect(Object.keys(getStructureOverview(property)).sort()).toEqual(["parameters", "profile", "rooms"]);
  });

  it("carries no value of the demo dataset anywhere, whoever the property is", () => {
    const demo = demoStructureOverview();
    const real = JSON.stringify(getStructureOverview(property));

    for (const value of [
      demo.profile.name,
      demo.profile.type,
      demo.profile.location,
      demo.profile.imageSrc,
      ...demo.rooms.flatMap((room) => [room.name, room.code]),
    ]) {
      expect(real).not.toContain(String(value));
    }
  });
});

describe("demoStructureOverview (explicit fixture: development and tests only)", () => {
  it("is the complete example of the approved reference", () => {
    const demo = demoStructureOverview();

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
    const { rooms, parameters, profile } = demoStructureOverview();
    const theoreticalGuests = rooms.reduce((sum, room) => sum + room.rooms * (room.maxAdults + room.maxChildren), 0);
    const roomCount = rooms.reduce((sum, room) => sum + room.rooms, 0);

    expect(parameters.maxGuests).toBe(92);
    expect(parameters.maxGuests).toBe(theoreticalGuests);
    expect(profile.roomCount).toBe(roomCount);
  });
});
