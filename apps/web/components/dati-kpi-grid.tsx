"use client";

import type { DataOverviewResponse } from "@ninfa/contracts";

import { datiCopy } from "@/lib/data/copy";
import { formatMonthName } from "@/lib/data/dates";
import {
  formatMoneyCents,
  formatMoneyWhole,
  formatSignedCount,
  formatSignedPercent,
} from "@/lib/data/format";
import { formatCount } from "@/lib/decisions/format";

import { DeltaChip } from "./dati-parts";

interface KpiProps {
  id: string;
  label: string;
  value: string | null;
  note: string;
  delta?: { text: string } | null;
  highlight?: boolean;
  unavailableNote?: string;
}

/** A KPI whose figure cannot be calculated shows "Non disponibile" and, in the note's place, WHY -
 * never a zero and never an empty tile. */
function Kpi({ id, label, value, note, delta, highlight = false, unavailableNote }: KpiProps) {
  const labelId = `${id}-label`;
  return (
    <article className={`dati-kpi${highlight ? " dati-kpi--highlight" : ""}`} aria-labelledby={labelId}>
      <h3 id={labelId} className="dati-kpi__label">
        {label}
      </h3>
      {value !== null ? (
        <p className="dati-kpi__value">{value}</p>
      ) : (
        <p className="dati-kpi__value dati-kpi__value--na">{datiCopy.notAvailable}</p>
      )}
      <p className="dati-kpi__note">{value !== null ? note : (unavailableNote ?? note)}</p>
      {value !== null && delta ? <DeltaChip text={delta.text} /> : null}
    </article>
  );
}

/**
 * The centre 2x2 block: the first card (room revenue) carries the NINFA-blue highlight the reference
 * gives its first KPI.
 *
 * - "Ricavi camera" is the room revenue ALREADY ON THE BOOKS, never "fatturato" or "incassi";
 * - ADR is the on-books average rate (revenue / room-nights), as NINFA defines it;
 * - "Camere-notte" are never called bookings;
 * - the cost KPI is the last CONCLUDED month by invoice date (the month in progress is not a cost of
 *   the month), and says which month it is.
 *
 * A delta is shown ONLY when the backend sent one, always names what it is compared with, and is a
 * neutral chip: there is no "good" or "bad" change in NINFA's data.
 */
export function DatiKpiGrid({ overview }: { overview: DataOverviewResponse }) {
  const { occupancy, costs, currency } = overview;
  const selected = occupancy.state === "AVAILABLE" ? occupancy.selected : null;
  const scope = datiCopy.period.nextDays(overview.period_days);

  const costMonth = formatMonthName(costs.month_start);
  const previousMonth = formatMonthName(costs.previous_month_start);
  const costAvailable = costs.state === "AVAILABLE" && costs.total_net_cost !== null;
  const roomNightsDelta = selected?.room_nights_delta_7d ?? null;
  const revenue = selected?.room_revenue ?? null;
  const adr = selected?.adr ?? null;
  const roomNights = selected?.room_nights ?? null;

  return (
    <div className="dati-kpis" role="group" aria-label={datiCopy.kpi.groupLabel}>
      <h2 className="visually-hidden">{datiCopy.kpi.groupLabel}</h2>
      <Kpi
        id="dati-kpi-revenue"
        highlight
        label={datiCopy.kpi.roomRevenue}
        value={revenue !== null ? formatMoneyWhole(revenue, currency) : null}
        note={`${datiCopy.kpi.roomRevenueNote} · ${scope}`}
      />
      <Kpi
        id="dati-kpi-adr"
        label={datiCopy.kpi.adr}
        value={adr !== null ? formatMoneyCents(adr, currency) : null}
        note={datiCopy.kpi.adrNote}
      />
      <Kpi
        id="dati-kpi-room-nights"
        label={datiCopy.kpi.roomNights}
        value={roomNights !== null ? formatCount(roomNights) : null}
        note={`${datiCopy.kpi.roomNightsNote} · ${scope}`}
        delta={
          roomNightsDelta !== null
            ? { text: datiCopy.kpi.deltaVsWeek(formatSignedCount(roomNightsDelta)) }
            : null
        }
      />
      <Kpi
        id="dati-kpi-costs"
        label={datiCopy.kpi.costs(costMonth)}
        value={costAvailable ? formatMoneyWhole(costs.total_net_cost, costs.currency) : null}
        note={datiCopy.kpi.costsNote}
        delta={
          costs.delta_pct !== null
            ? { text: datiCopy.kpi.deltaVsMonth(formatSignedPercent(costs.delta_pct), previousMonth) }
            : null
        }
        unavailableNote={datiCopy.costs.emptyBody}
      />
    </div>
  );
}
