"use client";

import type { DataOverviewResponse, DataPeriod, DataPeriodMetrics } from "@ninfa/contracts";

import { datiCopy, unavailableReasonText } from "@/lib/data/copy";
import { bookingsFreshnessLine } from "@/lib/data/freshness";
import { formatPercent } from "@/lib/data/format";

import { DatiCard, DatiEmpty } from "./dati-parts";
import { DatiPeriodControl } from "./dati-tabs";

export interface DatiOccupancyCardProps {
  overview: DataOverviewResponse;
  timeZone: string;
  period: DataPeriod;
  busy: boolean;
  onSelectPeriod: (period: DataPeriod) => void;
}

/** One honest line about WHICH nights the percentage rests on: nights without a stored booking
 * snapshot, and nights whose capacity is unknown, are never silently folded into it. */
function coverageNotes(metrics: DataPeriodMetrics): string[] {
  const notes: string[] = [];
  if (metrics.nights_with_data < metrics.nights_requested) {
    notes.push(datiCopy.occupancy.bookingsKnownFor(metrics.nights_with_data, metrics.nights_requested));
  }
  if (metrics.nights_with_data > 0) {
    if (metrics.nights_with_capacity === 0) {
      notes.push(datiCopy.occupancy.capacityUnknown);
    } else if (metrics.nights_with_capacity < metrics.nights_with_data) {
      notes.push(
        datiCopy.occupancy.capacityKnownFor(metrics.nights_with_capacity, metrics.nights_with_data),
      );
    }
  }
  return notes;
}

function MiniTile({
  label,
  metrics,
  detail,
}: {
  label: string;
  metrics: DataPeriodMetrics | null;
  detail: (metrics: DataPeriodMetrics) => string | null;
}) {
  const percent = metrics?.occupancy_pct ?? null;
  return (
    <li className="dati-tile">
      <p className="dati-tile__label">{label}</p>
      {metrics !== null && percent !== null ? (
        <>
          <p className="dati-tile__value">{formatPercent(percent)}</p>
          <p className="dati-tile__detail">{detail(metrics)}</p>
        </>
      ) : (
        <>
          <p className="dati-tile__value dati-tile__value--na">{datiCopy.notAvailable}</p>
          <p className="dati-tile__detail">
            {metrics !== null && metrics.room_nights !== null
              ? datiCopy.occupancy.roomNightsShort(metrics.room_nights)
              : " "}
          </p>
        </>
      )}
    </li>
  );
}

/**
 * The large left card: the on-books occupancy of the next N nights - the figure Dati leads with.
 *
 * Everything shown comes from the backend overview. The percentage is `rooms on books / rooms
 * available` over the nights with a KNOWN capacity only, and the card says so whenever some nights are
 * left out; room-nights are never called bookings; and when nothing can be calculated it shows a
 * designed "Non disponibile" with the reason, never a zero.
 */
export function DatiOccupancyCard({
  overview,
  timeZone,
  period,
  busy,
  onSelectPeriod,
}: DatiOccupancyCardProps) {
  const { occupancy } = overview;
  const selected = occupancy.selected;
  const available = occupancy.state === "AVAILABLE" && selected !== null;
  const percent = selected?.occupancy_pct ?? null;
  const freshness = bookingsFreshnessLine(
    overview.freshness.bookings,
    overview.as_of_local_date,
    timeZone,
  );

  return (
    <DatiCard
      id="dati-occupancy"
      title={datiCopy.occupancy.title}
      className="dati-occupancy"
      actions={<span className="dati-card__basis">{datiCopy.occupancy.basis}</span>}
    >
      {available ? (
        <div className="dati-occupancy__hero" aria-busy={busy}>
          {percent !== null ? (
            <p className="dati-occupancy__value">{formatPercent(percent)}</p>
          ) : (
            <p className="dati-occupancy__value dati-occupancy__value--na">{datiCopy.notAvailable}</p>
          )}
          <p className="dati-occupancy__scope">
            {datiCopy.period.nextDays(overview.period_days)}
            {selected.room_nights !== null
              ? ` · ${datiCopy.occupancy.roomNightsBooked(selected.room_nights)}`
              : ""}
          </p>
          {coverageNotes(selected).map((note) => (
            <p key={note} className="dati-occupancy__note">
              {note}
            </p>
          ))}
        </div>
      ) : (
        <DatiEmpty
          title={datiCopy.occupancy.unavailableTitle}
          body={unavailableReasonText(occupancy.reason)}
        />
      )}

      <DatiPeriodControl period={period} onSelect={onSelectPeriod} busy={busy} />

      <ul className="dati-occupancy__tiles" aria-label={datiCopy.occupancy.miniTilesLabel}>
        <MiniTile
          label={datiCopy.occupancy.todayTile}
          metrics={occupancy.today}
          detail={(metrics) =>
            metrics.rooms_on_books_with_capacity !== null && metrics.rooms_available !== null
              ? datiCopy.occupancy.roomsOfAvailable(
                  metrics.rooms_on_books_with_capacity,
                  metrics.rooms_available,
                )
              : null
          }
        />
        <MiniTile
          label={datiCopy.occupancy.sevenTile}
          metrics={occupancy.days_7}
          detail={(metrics) =>
            metrics.room_nights !== null ? datiCopy.occupancy.roomNightsShort(metrics.room_nights) : null
          }
        />
        <MiniTile
          label={datiCopy.occupancy.thirtyTile}
          metrics={occupancy.days_30}
          detail={(metrics) =>
            metrics.room_nights !== null ? datiCopy.occupancy.roomNightsShort(metrics.room_nights) : null
          }
        />
      </ul>

      <p className="dati-occupancy__fresh" data-kind={freshness.kind}>
        {freshness.text}
      </p>
    </DatiCard>
  );
}
