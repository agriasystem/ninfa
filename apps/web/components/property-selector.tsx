"use client";

import type { PropertyAccess } from "@ninfa/contracts";

import { copy } from "@/lib/copy";

import { ChevronDownIcon } from "./icons";

export interface PropertySelectorProps {
  properties: PropertyAccess[];
  selectedPropertyId: string;
  onSelect: (propertyId: string) => void;
}

/**
 * Only rendered when there is a real choice to make (Gate 14 spec: 0 -> empty state elsewhere, 1
 * -> auto-selected, no selector shown at all). Every option comes from the authenticated
 * SessionContext - there is no free-text/UUID input, so an arbitrary id can never be typed in.
 *
 * Home UI V1: it lives in the page header, styled as the property NAME with a chevron (the approved
 * reference); it stays a native, keyboard-operable `<select>` whose accessible label is
 * `copy.property.selectorLabel` (visually hidden - the name itself is the visible label).
 */
export function PropertySelector({ properties, selectedPropertyId, onSelect }: PropertySelectorProps) {
  if (properties.length <= 1) {
    return null;
  }

  return (
    <label className="property-selector">
      <span className="property-selector__label visually-hidden">{copy.property.selectorLabel}</span>
      <select value={selectedPropertyId} onChange={(event) => onSelect(event.target.value)}>
        {properties.map((property) => (
          <option key={property.id} value={property.id}>
            {property.name}
          </option>
        ))}
      </select>
      <ChevronDownIcon className="property-selector__chevron" />
    </label>
  );
}
