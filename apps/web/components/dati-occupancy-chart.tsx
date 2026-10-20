"use client";

import type { DataNightRow, DataOverviewResponse } from "@ninfa/contracts";

import { datiCopy, nightStatusText, unavailableReasonText } from "@/lib/data/copy";
import {
  formatDayMonthShort,
  formatNightLong,
  formatNightTick,
} from "@/lib/data/dates";
import { formatPercent } from "@/lib/data/format";

import { DatiCard, DatiEmpty } from "./dati-parts";

/** The tallest value the axis must reach, in percent. Occupancy is stored NOT clamped (45 rooms on 40
 * available is 112,5 %), so the axis grows in steps of 25 when a night exceeds 100 - the bars are
 * pure geometry of the figures the backend sent. */
function axisMaxOf(nights: readonly DataNightRow[]): number {
  let max = 100;
  for (const night of nights) {
    const value = night.occupancy_pct === null ? null : Number.parseFloat(night.occupancy_pct);
    if (value !== null && Number.isFinite(value) && value > max) max = value;
  }
  return Math.ceil(max / 25) * 25;
}

function heightPercent(occupancy: string, axisMax: number): number {
  const value = Number.parseFloat(occupancy);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(100, (value / axisMax) * 100);
}

type Slot =
  | { kind: "bar"; night: DataNightRow; occupancy: string; height: number }
  | { kind: "unknown-capacity"; night: DataNightRow }
  | { kind: "no-data"; night: DataNightRow };

function slotOf(night: DataNightRow, axisMax: number): Slot {
  if (!night.has_data) return { kind: "no-data", night };
  if (night.occupancy_pct === null) return { kind: "unknown-capacity", night };
  return { kind: "bar", night, occupancy: night.occupancy_pct, height: heightPercent(night.occupancy_pct, axisMax) };
}

function tipOf(slot: Slot): string {
  const day = formatNightLong(slot.night.stay_date);
  const flagged = slot.night.status === "ATTENTION" ? ` · ${datiCopy.chart.attentionTip}` : "";
  switch (slot.kind) {
    case "bar":
      return `${day}: ${formatPercent(slot.occupancy)}${flagged}`;
    case "unknown-capacity":
      return `${day}: ${datiCopy.chart.unknownCapacityTip}${flagged}`;
    case "no-data":
      return `${day}: ${datiCopy.chart.noDataTip}`;
  }
}

/** Which columns carry an x-axis label: every night for a week, a regular step for a month. */
function showsTick(index: number, total: number): boolean {
  return total <= 7 ? true : index % 5 === 0;
}

// The silhouette shown BEHIND an empty state, so the card never reads as a broken blank area.
const GHOST_HEIGHTS = [38, 52, 44, 66, 58, 72, 49, 61, 43, 55, 69, 47];

/**
 * The principal analytical visual: occupancy per stay night, as NINFA-blue bars (Dati UI V1).
 *
 * - A bar is the stored on-books occupancy of that night; a night whose capacity is unknown has NO bar
 *   (a hatched slot, never 0 %), and a night with no snapshot at all is an empty slot;
 * - a discreet orange marker sits above a night that has an actual NINFA decision - it does not say how
 *   serious it is (NINFA has no severity) and it is never the only signal (tooltip, legend and the
 *   table equivalent all say "Richiede attenzione");
 * - there is no target line and no expected level: none exists deterministically for a night;
 * - the figure has a text equivalent: a visually hidden table with the same values, and the visible
 *   detail table below carries the same numbers.
 *
 * Plain HTML/CSS, no charting library: nothing is added to the dependencies, and `prefers-reduced-motion`
 * is respected by the CSS (the bars do not animate).
 */
export function DatiOccupancyChart({ overview }: { overview: DataOverviewResponse }) {
  const { occupancy } = overview;
  const nights = occupancy.nights;
  const days = overview.period_days;
  const title = datiCopy.chart.title(days);
  const hasAnyFigure = nights.some((night) => night.occupancy_pct !== null);

  if (occupancy.state !== "AVAILABLE" || nights.length === 0 || !hasAnyFigure) {
    return (
      <DatiCard id="dati-chart" title={title} className="dati-chart">
        <div className="dati-chart__empty">
          <div className="dati-chart__ghost" aria-hidden="true">
            {GHOST_HEIGHTS.map((height, index) => (
              <span key={index} style={{ height: `${height}%` }} />
            ))}
          </div>
          <DatiEmpty
            title={datiCopy.chart.emptyTitle}
            body={unavailableReasonText(occupancy.state === "AVAILABLE" ? "NO_DATA" : occupancy.reason)}
          />
        </div>
      </DatiCard>
    );
  }

  const axisMax = axisMaxOf(nights);
  const ticks = [0, 1, 2, 3, 4].map((step) => (axisMax / 4) * step);
  const slots = nights.map((night) => slotOf(night, axisMax));
  const hasAttention = nights.some((night) => night.status === "ATTENTION");
  const hasUnknownCapacity = slots.some((slot) => slot.kind === "unknown-capacity");

  return (
    <DatiCard id="dati-chart" title={title} className="dati-chart">
      <p className="dati-chart__subtitle">{datiCopy.chart.subtitle}</p>
      <figure className="dati-chart__figure">
        <div className="dati-chart__plot-wrap">
          <ol className="dati-chart__axis" aria-hidden="true">
            {[...ticks].reverse().map((tick) => (
              <li key={tick}>{formatPercent(String(tick), 0)}</li>
            ))}
          </ol>
          <div className="dati-chart__plot" role="img" aria-label={datiCopy.chart.ariaSummary(days)}>
            <div className="dati-chart__grid" aria-hidden="true">
              {ticks.map((tick) => (
                <span key={tick} />
              ))}
            </div>
            <ol className="dati-chart__bars" data-count={nights.length}>
              {slots.map((slot, index) => (
                <li
                  key={slot.night.stay_date}
                  className={`dati-chart__col dati-chart__col--${slot.kind}`}
                  title={tipOf(slot)}
                >
                  <span className="dati-chart__area">
                    {slot.night.status === "ATTENTION" ? (
                      <span
                        className="dati-chart__marker"
                        style={slot.kind === "bar" ? { bottom: `calc(${slot.height}% + 6px)` } : undefined}
                        aria-hidden="true"
                      />
                    ) : null}
                    {slot.kind === "bar" ? (
                      <span className="dati-chart__bar" style={{ height: `${slot.height}%` }} />
                    ) : (
                      <span className="dati-chart__slot" />
                    )}
                  </span>
                  <span className="dati-chart__tick" aria-hidden="true">
                    {showsTick(index, nights.length)
                      ? nights.length <= 7
                        ? formatNightTick(slot.night.stay_date)
                        : formatDayMonthShort(slot.night.stay_date)
                      : ""}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>

        {hasAttention || hasUnknownCapacity ? (
          <figcaption className="dati-chart__legend">
            {hasAttention ? (
              <span className="dati-chart__legend-item">
                <span className="dati-chart__marker dati-chart__marker--static" aria-hidden="true" />
                {datiCopy.chart.attentionLegend}
              </span>
            ) : null}
            {hasUnknownCapacity ? (
              <span className="dati-chart__legend-item">
                <span className="dati-chart__legend-hatch" aria-hidden="true" />
                {datiCopy.chart.unknownCapacityLegend}
              </span>
            ) : null}
          </figcaption>
        ) : null}

        {/* A <table> ignores width:1px, so the hidden equivalent lives in a clipping wrapper: the
            table is read by assistive technology but contributes no layout overflow. */}
        <div className="visually-hidden">
          <table>
            <caption>{datiCopy.chart.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{datiCopy.chart.colNight}</th>
                <th scope="col">{datiCopy.chart.colOccupancy}</th>
                <th scope="col">{datiCopy.table.colStatus}</th>
              </tr>
            </thead>
            <tbody>
              {nights.map((night) => (
                <tr key={night.stay_date}>
                  <th scope="row">{formatNightLong(night.stay_date)}</th>
                  <td>{night.occupancy_pct !== null ? formatPercent(night.occupancy_pct) : datiCopy.notAvailable}</td>
                  <td>{nightStatusText(night.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </figure>
    </DatiCard>
  );
}
