"use client";

import type { PropertyAccess } from "@ninfa/contracts";

import { formatPropertyLocalDateLongItalian } from "@/lib/date/property-date";

import { PropertySelector } from "./property-selector";

export interface PropertyHeaderProps {
  properties: PropertyAccess[];
  selectedPropertyId: string;
  onSelect: (propertyId: string) => void;
}

/**
 * The top-right of the content area (Home UI V1): the REAL property name and, under it, today's
 * date in the PROPERTY's own timezone ("8 ottobre 2026") - never the browser's. With one property
 * the name is static text (no chevron that would promise a choice that does not exist); with
 * several, the existing `PropertySelector` takes the name's place. Nothing here is hardcoded.
 */
export function PropertyHeader({ properties, selectedPropertyId, onSelect }: PropertyHeaderProps) {
  const selected = properties.find((property) => property.id === selectedPropertyId);
  if (!selected) return null;

  return (
    <div className="property-header">
      {properties.length > 1 ? (
        <PropertySelector
          properties={properties}
          selectedPropertyId={selectedPropertyId}
          onSelect={onSelect}
        />
      ) : (
        <p className="property-header__name">{selected.name}</p>
      )}
      <p className="property-header__date">
        {formatPropertyLocalDateLongItalian(new Date(), selected.timezone)}
      </p>
    </div>
  );
}
