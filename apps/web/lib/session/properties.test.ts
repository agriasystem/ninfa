import { describe, expect, it } from "vitest";

import type { PropertyAccess, SessionContextResponse, WorkspaceAccess } from "@ninfa/contracts";

import { allAccessibleProperties, resolveSelectedProperty } from "./properties";

function property(id: string, slug: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name: slug.toUpperCase(), slug, timezone };
}

function workspace(id: string, slug: string, properties: PropertyAccess[]): WorkspaceAccess {
  return { id, name: slug.toUpperCase(), slug, role: "MEMBER", properties };
}

function session(workspaces: WorkspaceAccess[]): SessionContextResponse {
  return {
    user: { id: "user-1", email: "user@example.com", display_name: null },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces,
  };
}

describe("allAccessibleProperties", () => {
  it("flattens properties across every accessible workspace", () => {
    const propA = property("prop-a", "alpha");
    const propB = property("prop-b", "beta");
    const s = session([workspace("ws-1", "one", [propA]), workspace("ws-2", "two", [propB])]);

    expect(allAccessibleProperties(s)).toEqual([propA, propB]);
  });

  it("is empty when there are zero accessible properties", () => {
    expect(allAccessibleProperties(session([]))).toEqual([]);
  });
});

describe("resolveSelectedProperty", () => {
  it("returns null when the user has zero accessible properties (empty state)", () => {
    expect(resolveSelectedProperty(session([]), null)).toBeNull();
    expect(resolveSelectedProperty(session([]), "some-id")).toBeNull();
  });

  it("auto-selects the single property when there is exactly one", () => {
    const prop = property("prop-a", "alpha");
    const s = session([workspace("ws-1", "one", [prop])]);

    expect(resolveSelectedProperty(s, null)).toEqual(prop);
  });

  it("honours the requested property id when it IS accessible", () => {
    const propA = property("prop-a", "alpha");
    const propB = property("prop-b", "beta");
    const s = session([workspace("ws-1", "one", [propA, propB])]);

    expect(resolveSelectedProperty(s, "prop-b")).toEqual(propB);
  });

  it("falls back to the first accessible property for an unknown/foreign id - never invents one", () => {
    const propA = property("prop-a", "alpha");
    const propB = property("prop-b", "beta");
    const s = session([workspace("ws-1", "one", [propA, propB])]);

    expect(resolveSelectedProperty(s, "some-other-workspace-property")).toEqual(propA);
  });

  it("falls back to the first accessible property when none was requested and there are several", () => {
    const propA = property("prop-a", "alpha");
    const propB = property("prop-b", "beta");
    const s = session([workspace("ws-1", "one", [propA, propB])]);

    expect(resolveSelectedProperty(s, null)).toEqual(propA);
  });
});
