"use client";

import Link from "next/link";

import type { DataOverviewResponse } from "@ninfa/contracts";

import { datiCopy } from "@/lib/data/copy";
import { strutturaInventoryRoute } from "@/lib/routes";

/**
 * "Prenotazioni superiori all'inventario": on some nights the bookings hold more rooms than the room inventory
 * says exist. NINFA cannot tell whether the inventory is too low, the hotel is really overbooked or a booking
 * is wrong, so it says only that the two disagree and where to look - the occupancy over 100 % stays on the
 * page exactly as stored, and nothing here is a decision (no severity, no colour of alarm).
 *
 * The count is the backend's (`inventory_consistency`), over the 30 observed nights whatever period is shown;
 * the link is the one Dati already uses to reach the room inventory in Struttura.
 */
export function DatiInventoryNotice({
  overview,
  propertyId,
}: {
  overview: DataOverviewResponse;
  propertyId: string;
}) {
  const { occupancy } = overview;
  const nights = occupancy.inventory_consistency.over_capacity_nights;
  if (occupancy.state !== "AVAILABLE" || nights === 0) return null;
  const copy = datiCopy.consistency;
  return (
    <section className="dati-notice" aria-labelledby="dati-inventory-notice-title">
      <div className="dati-notice__text">
        <h2 id="dati-inventory-notice-title" className="dati-notice__title">
          {copy.title}
        </h2>
        <p className="dati-notice__body">{copy.body(nights)}</p>
      </div>
      <Link className="dati-cta dati-cta--inline" href={strutturaInventoryRoute(propertyId)}>
        {copy.action}
      </Link>
    </section>
  );
}
