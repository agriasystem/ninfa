"use client";

import type { PropertyAccess } from "@ninfa/contracts";

import { copy } from "@/lib/copy";

export interface PropertySelectorProps {
  properties: PropertyAccess[];
  selectedPropertyId: string;
  onSelect: (propertyId: string) => void;
}

/**
 * Only rendered when there is a real choice to make (Gate 14 spec: 0 -> empty state elsewhere, 1
 * -> auto-selected, no selector shown at all). Every option comes from the authenticated
 * SessionContext - there is no free-text/UUID input, so an arbitrary id can never be typed in.
 */
export function PropertySelector({ properties, selectedPropertyId, onSelect }: PropertySelectorProps) {
  if (properties.length <= 1) {
    return null;
  }

  return (
    <label className="property-selector">
      <span className="property-selector__label">{copy.property.selectorLabel}</span>
      <select value={selectedPropertyId} onChange={(event) => onSelect(event.target.value)}>
        {properties.map((property) => (
          <option key={property.id} value={property.id}>
            {property.name}
          </option>
        ))}
      </select>
    </label>
  );
}
