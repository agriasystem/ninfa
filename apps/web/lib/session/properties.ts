import type { PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

/** Every property the session grants access to, flattened across all workspaces. There is no
 * workspace switcher in Gate 14 - the property selector is the only scoping control. */
export function allAccessibleProperties(session: SessionContextResponse): PropertyAccess[] {
  return session.workspaces.flatMap((workspace) => workspace.properties);
}

/**
 * Which property is "selected", given what the URL/state asked for and the session's REAL access
 * list. An unknown or foreign id is never trusted: it silently falls back to the first
 * accessible property (deterministic, since the backend already orders properties by slug) -
 * never a client-side error, and the backend's own authorization remains the last real barrier
 * regardless of what this picks.
 */
export function resolveSelectedProperty(
  session: SessionContextResponse,
  requestedPropertyId: string | null,
): PropertyAccess | null {
  const properties = allAccessibleProperties(session);
  if (properties.length === 0) return null;
  const requested =
    requestedPropertyId !== null
      ? properties.find((property) => property.id === requestedPropertyId)
      : undefined;
  return requested ?? properties[0] ?? null;
}
