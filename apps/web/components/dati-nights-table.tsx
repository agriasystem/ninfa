"use client";

import Link from "next/link";
import { useId, useMemo, useState } from "react";

import type { DataNightRow, DataOverviewResponse } from "@ninfa/contracts";

import { datiCopy, unavailableReasonText } from "@/lib/data/copy";
import { formatNightShort, nightSearchText } from "@/lib/data/dates";
import { formatMoneyCents, formatMoneyWhole, formatPercent, formatSignedCount } from "@/lib/data/format";
import { formatCount } from "@/lib/decisions/format";
import { decisionDetailRoute } from "@/lib/routes";

import { DatiCard, DatiEmpty, StatusMark } from "./dati-parts";

export interface DatiNightsTableProps {
  overview: DataOverviewResponse;
  propertyId: string;
  /** `overview`: the Panoramica's table. `bookings`: the Prenotazioni tab adds the per-night booking
   * count and the comparison with the snapshot of 7 days ago. */
  variant?: "overview" | "bookings";
}

/** A figure the backend could not calculate is a dash with a spoken "non disponibile" - never 0. */
function Cell({ children, missing = false }: { children: string; missing?: boolean }) {
  return missing ? (
    <span aria-label={datiCopy.table.noData} className="dati-na">
      —
    </span>
  ) : (
    <>{children}</>
  );
}

function Row({
  night,
  propertyId,
  currency,
  variant,
}: {
  night: DataNightRow;
  propertyId: string;
  currency: string;
  variant: "overview" | "bookings";
}) {
  const status = <StatusMark status={night.status} />;
  return (
    <tr data-status={night.status.toLowerCase()}>
      <th scope="row" className="dati-table__date">
        {formatNightShort(night.stay_date)}
      </th>
      {variant === "bookings" ? (
        <td>
          <Cell missing={night.bookings === null}>{formatCount(night.bookings)}</Cell>
        </td>
      ) : null}
      <td>
        <Cell missing={night.rooms_on_books === null}>{formatCount(night.rooms_on_books)}</Cell>
      </td>
      <td>
        <Cell missing={night.rooms_available === null}>{formatCount(night.rooms_available)}</Cell>
      </td>
      <td>
        <Cell missing={night.occupancy_pct === null}>{formatPercent(night.occupancy_pct)}</Cell>
      </td>
      <td>
        <Cell missing={night.room_revenue === null}>{formatMoneyWhole(night.room_revenue, currency)}</Cell>
      </td>
      <td>
        <Cell missing={night.adr === null}>{formatMoneyCents(night.adr, currency)}</Cell>
      </td>
      {variant === "bookings" ? (
        <>
          <td>
            <Cell missing={night.rooms_on_books_7d_ago === null}>
              {formatCount(night.rooms_on_books_7d_ago)}
            </Cell>
          </td>
          <td>
            <Cell missing={night.rooms_delta_7d === null}>{formatSignedCount(night.rooms_delta_7d)}</Cell>
          </td>
        </>
      ) : null}
      <td className="dati-table__status">
        {night.decision_id !== null ? (
          <Link
            href={decisionDetailRoute(propertyId, night.decision_id)}
            className="dati-table__decision"
            aria-label={`${datiCopy.table.openDecision}: ${formatNightShort(night.stay_date)}`}
          >
            {status}
          </Link>
        ) : (
          status
        )}
      </td>
    </tr>
  );
}

/**
 * "Dettaglio soggiorni": one row per stay night with the figures the backend stored for it.
 *
 * - NO OTA column: no per-day OTA share is defined anywhere in NINFA (the OTA share is a 30-night
 *   metric), and a day-level figure faked from it would be a lie;
 * - "Stato" is the backend's own night status, as a WORD (never colour alone) - and only a night that
 *   really has a decision is a link, to that decision's detail page: no other row is interactive;
 * - a night with no snapshot is a dash and "Non valutato", never a zero;
 * - search by date and an attention-only filter are the only controls, and both only narrow the rows
 *   the backend sent: nothing is re-sorted, recomputed or re-thresholded here.
 */
export function DatiNightsTable({ overview, propertyId, variant = "overview" }: DatiNightsTableProps) {
  const { occupancy, currency } = overview;
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);

  const nights = occupancy.nights;
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("it-IT");
    return nights.filter(
      (night) =>
        (!attentionOnly || night.status === "ATTENTION") &&
        (needle === "" || nightSearchText(night.stay_date).includes(needle)),
    );
  }, [nights, query, attentionOnly]);

  if (occupancy.state !== "AVAILABLE" || nights.length === 0) {
    return (
      <DatiCard id={`dati-table-${variant}`} title={datiCopy.table.title} className="dati-table-card">
        <DatiEmpty
          title={datiCopy.occupancy.unavailableTitle}
          body={unavailableReasonText(occupancy.reason ?? "NO_BOOKING_DATA")}
        />
      </DatiCard>
    );
  }

  const columns = variant === "bookings" ? 10 : 7;
  return (
    <DatiCard
      id={`dati-table-${variant}`}
      title={datiCopy.table.title}
      className="dati-table-card"
      actions={
        <div className="dati-table__controls">
          <label className="dati-table__search" htmlFor={searchId}>
            <span className="visually-hidden">{datiCopy.table.searchLabel}</span>
            <input
              id={searchId}
              type="search"
              value={query}
              placeholder={datiCopy.table.searchPlaceholder}
              onChange={(event) => setQuery(event.target.value)}
              autoComplete="off"
            />
          </label>
          <button
            type="button"
            className="dati-table__filter"
            aria-pressed={attentionOnly}
            onClick={() => setAttentionOnly((current) => !current)}
          >
            {datiCopy.table.attentionOnly}
          </button>
        </div>
      }
    >
      {/* A scrollable region must be reachable by keyboard: tabindex + a name. */}
      <div className="dati-table__scroll" role="region" aria-label={datiCopy.table.scrollRegion} tabIndex={0}>
        <table className="dati-table">
          <caption className="visually-hidden">{datiCopy.table.caption}</caption>
          <thead>
            <tr>
              <th scope="col">{datiCopy.table.colDate}</th>
              {variant === "bookings" ? <th scope="col">{datiCopy.table.colBookings}</th> : null}
              <th scope="col">{datiCopy.table.colRoomsBooked}</th>
              <th scope="col">{datiCopy.table.colAvailable}</th>
              <th scope="col">{datiCopy.table.colOccupancy}</th>
              <th scope="col">{datiCopy.table.colRevenue}</th>
              <th scope="col">{datiCopy.table.colAdr}</th>
              {variant === "bookings" ? (
                <>
                  <th scope="col">{datiCopy.table.colSevenAgo}</th>
                  <th scope="col">{datiCopy.table.colChange}</th>
                </>
              ) : null}
              <th scope="col" className="dati-table__status">
                {datiCopy.table.colStatus}
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.length > 0 ? (
              visible.map((night) => (
                <Row
                  key={night.stay_date}
                  night={night}
                  propertyId={propertyId}
                  currency={currency}
                  variant={variant}
                />
              ))
            ) : (
              <tr>
                <td colSpan={columns} className="dati-table__none">
                  {datiCopy.table.empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="dati-table__foot" aria-live="polite">
        <span>{datiCopy.table.shown(visible.length, nights.length)}</span>
        <span>{datiCopy.table.notePartial}</span>
      </p>
    </DatiCard>
  );
}
