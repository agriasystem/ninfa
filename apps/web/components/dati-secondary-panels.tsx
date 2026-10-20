"use client";

import Link from "next/link";

import type { AnalysisDomain, DataOverviewResponse, DataPeriod, DataPeriodMetrics } from "@ninfa/contracts";

import { analysisDomainLabels } from "@/lib/copy";
import {
  costCategoryLabel,
  cporStatusText,
  datiCopy,
  domainStateText,
  laborCategoryLabel,
  unavailableReasonText,
} from "@/lib/data/copy";
import { formatDateRange, formatMonthName } from "@/lib/data/dates";
import {
  formatMoneyCents,
  formatMoneyWhole,
  formatPercent,
  formatSignedCount,
  formatSignedPercent,
} from "@/lib/data/format";
import { bookingsFreshnessLine, domainFreshnessLine } from "@/lib/data/freshness";
import { formatCount, formatHours } from "@/lib/decisions/format";
import { decisionDetailRoute } from "@/lib/routes";

import { DatiDistributionCard } from "./dati-distribution-card";
import { DatiCard, DatiEmpty, DeltaChip } from "./dati-parts";
import { DatiNightsTable } from "./dati-nights-table";
import { DatiOccupancyChart } from "./dati-occupancy-chart";
import type { DatiPanelProps } from "./dati-overview-panel";
import { DatiPeriodControl } from "./dati-tabs";

/** One line stating a domain's analysis state and its own freshness - shown at the foot of a tab. */
function DomainFacts({
  overview,
  domain,
  freshness,
}: {
  overview: DataOverviewResponse;
  domain: AnalysisDomain;
  freshness: { kind: "known" | "unknown"; text: string };
}) {
  const state = overview.analysis.domain_states.find((item) => item.domain === domain)?.state ?? "UNKNOWN";
  return (
    <ul className="dati-facts">
      <li>
        <span className="dati-facts__label">{analysisDomainLabels[domain]}</span>{" "}
        <span>{domainStateText(domain, state)}</span>
      </li>
      <li data-kind={freshness.kind}>{freshness.text}</li>
    </ul>
  );
}

// --- Prenotazioni -----------------------------------------------------------------------------------

function PeriodRow({
  label,
  metrics,
  currency,
}: {
  label: string;
  metrics: DataPeriodMetrics | null;
  currency: string;
}) {
  const na = (
    <span aria-label={datiCopy.table.noData} className="dati-na">
      —
    </span>
  );
  const occupancy = metrics?.occupancy_pct ?? null;
  const roomNights = metrics?.room_nights ?? null;
  const available = metrics?.rooms_available ?? null;
  const revenue = metrics?.room_revenue ?? null;
  const adr = metrics?.adr ?? null;
  const delta = metrics?.room_nights_delta_7d ?? null;
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{occupancy !== null ? formatPercent(occupancy) : na}</td>
      <td>{roomNights !== null ? formatCount(roomNights) : na}</td>
      <td>{available !== null ? formatCount(available) : na}</td>
      <td>{revenue !== null ? formatMoneyWhole(revenue, currency) : na}</td>
      <td>{adr !== null ? formatMoneyCents(adr, currency) : na}</td>
      <td>{delta !== null ? <DeltaChip text={formatSignedCount(delta)} /> : na}</td>
    </tr>
  );
}

export interface DatiBookingsPanelProps extends DatiPanelProps {
  period: DataPeriod;
  busy: boolean;
  onSelectPeriod: (period: DataPeriod) => void;
}

/** Prenotazioni: the same stored on-books data as Panoramica, read for detail - three periods side by
 * side, and every night with its booking count and its change against the snapshot of a week ago. */
export function DatiBookingsPanel({
  overview,
  propertyId,
  timeZone,
  period,
  busy,
  onSelectPeriod,
}: DatiBookingsPanelProps) {
  const { occupancy, currency } = overview;
  const freshness = bookingsFreshnessLine(overview.freshness.bookings, overview.as_of_local_date, timeZone);
  return (
    <div className="dati-stack" aria-busy={busy}>
      <DatiCard
        id="dati-summary"
        title={datiCopy.summary.title}
        className="dati-summary-card"
        actions={<DatiPeriodControl period={period} onSelect={onSelectPeriod} busy={busy} />}
      >
        {occupancy.state === "AVAILABLE" ? (
          <>
            <div className="dati-table__scroll" role="region" aria-label={datiCopy.scrollable(datiCopy.summary.title)} tabIndex={0}>
              <table className="dati-table dati-table--summary">
                <caption className="visually-hidden">{datiCopy.summary.caption}</caption>
                <thead>
                  <tr>
                    <th scope="col">{datiCopy.summary.colPeriod}</th>
                    <th scope="col">{datiCopy.summary.colOccupancy}</th>
                    <th scope="col">{datiCopy.summary.colRoomNights}</th>
                    <th scope="col">{datiCopy.summary.colAvailable}</th>
                    <th scope="col">{datiCopy.summary.colRevenue}</th>
                    <th scope="col">{datiCopy.summary.colAdr}</th>
                    <th scope="col">{datiCopy.summary.colChange}</th>
                  </tr>
                </thead>
                <tbody>
                  <PeriodRow label={datiCopy.summary.today} metrics={occupancy.today} currency={currency} />
                  <PeriodRow label={datiCopy.period.days7} metrics={occupancy.days_7} currency={currency} />
                  <PeriodRow label={datiCopy.period.days30} metrics={occupancy.days_30} currency={currency} />
                </tbody>
              </table>
            </div>
            <p className="dati-note">{datiCopy.summary.capacityNote}</p>
            <p className="dati-note">{datiCopy.summary.changeNote}</p>
          </>
        ) : (
          <DatiEmpty
            title={datiCopy.occupancy.unavailableTitle}
            body={unavailableReasonText(occupancy.reason)}
          />
        )}
        <p className="dati-card__fresh" data-kind={freshness.kind}>
          {freshness.text}
        </p>
      </DatiCard>

      <div className="dati-grid dati-grid--bookings">
        <div className="dati-cell dati-cell--chart">
          <DatiOccupancyChart overview={overview} />
        </div>
        <div className="dati-cell dati-cell--table">
          <DatiNightsTable overview={overview} propertyId={propertyId} variant="bookings" />
        </div>
      </div>
    </div>
  );
}

// --- Distribuzione ----------------------------------------------------------------------------------

export function DatiDistributionPanel({ overview, propertyId, timeZone }: DatiPanelProps) {
  const freshness = bookingsFreshnessLine(overview.freshness.bookings, overview.as_of_local_date, timeZone);
  return (
    <div className="dati-grid dati-grid--distribution">
      <div className="dati-cell dati-cell--wide">
        <DatiDistributionCard distribution={overview.distribution} propertyId={propertyId} variant="full" />
      </div>
      <div className="dati-cell dati-cell--aside">
        <DatiCard id="dati-distribution-info" title={datiCopy.distribution.infoTitle} className="dati-info">
          <dl className="dati-defs">
            <div>
              <dt>{datiCopy.distribution.defOtaTerm}</dt>
              <dd>{datiCopy.distribution.defOtaText}</dd>
            </div>
            <div>
              <dt>{datiCopy.distribution.defWeightTerm}</dt>
              <dd>{datiCopy.distribution.defWeightText}</dd>
            </div>
            <div>
              <dt>{datiCopy.distribution.defReferenceTerm}</dt>
              <dd>{datiCopy.distribution.defReferenceText}</dd>
            </div>
          </dl>
          <DomainFacts overview={overview} domain="DISTRIBUTION" freshness={freshness} />
        </DatiCard>
      </div>
    </div>
  );
}

// --- Costi ------------------------------------------------------------------------------------------

export function DatiCostsPanel({ overview, propertyId, timeZone }: DatiPanelProps) {
  const { costs } = overview;
  const month = formatMonthName(costs.month_start);
  const previousMonth = formatMonthName(costs.previous_month_start);
  const freshness = domainFreshnessLine(
    datiCopy.freshness.costs,
    overview.freshness.costs,
    overview.as_of_local_date,
    timeZone,
  );
  const state = overview.analysis.domain_states.find((item) => item.domain === "COSTS")?.state;
  const available = costs.state === "AVAILABLE" && costs.total_net_cost !== null;

  return (
    <div className="dati-grid dati-grid--costs">
      <div className="dati-cell dati-cell--summary">
        <DatiCard id="dati-costs-summary" title={datiCopy.costs.summaryTitle(month)} className="dati-cost-summary">
          {available ? (
            <>
              <p className="dati-cost-summary__label">{datiCopy.costs.total}</p>
              <p className="dati-cost-summary__value">{formatMoneyWhole(costs.total_net_cost, costs.currency)}</p>
              {costs.delta_pct !== null ? (
                <DeltaChip
                  text={datiCopy.costs.deltaVsMonth(formatSignedPercent(costs.delta_pct), previousMonth)}
                />
              ) : null}
              {costs.classification_coverage_pct !== null ? (
                <p className="dati-note">
                  {datiCopy.costs.classification(formatPercent(costs.classification_coverage_pct))}
                </p>
              ) : null}
            </>
          ) : (
            <DatiEmpty
              title={datiCopy.costs.emptyTitle}
              body={costs.reason === "NO_DATA" ? datiCopy.costs.emptyBody : unavailableReasonText(costs.reason)}
            />
          )}
          {costs.other_currencies_present ? <p className="dati-note">{datiCopy.costs.otherCurrencies}</p> : null}
          <p className="dati-note">{datiCopy.costs.basis}</p>
          {state === "NOT_ANALYZED" ? <p className="dati-note">{datiCopy.costs.notAnalyzedNote}</p> : null}
          <DomainFacts overview={overview} domain="COSTS" freshness={freshness} />
        </DatiCard>
      </div>

      <div className="dati-cell dati-cell--list">
        <DatiCard id="dati-costs-categories" title={datiCopy.costs.categoriesTitle} className="dati-cost-table-card">
          {available && costs.categories.length > 0 ? (
            <div className="dati-table__scroll" role="region" aria-label={datiCopy.scrollable(datiCopy.costs.categoriesTitle)} tabIndex={0}>
              <table className="dati-table dati-table--categories">
                <caption className="visually-hidden">{datiCopy.costs.caption}</caption>
                <thead>
                  <tr>
                    <th scope="col">{datiCopy.costs.colCategory}</th>
                    <th scope="col">{datiCopy.costs.colNet}</th>
                    <th scope="col">{datiCopy.costs.colCpor}</th>
                  </tr>
                </thead>
                <tbody>
                  {costs.categories.map((row) => (
                    <tr key={row.category}>
                      <th scope="row">
                        {costCategoryLabel(row.category)}
                        {row.decision_id !== null ? (
                          <Link
                            className="dati-inline-attention"
                            href={decisionDetailRoute(propertyId, row.decision_id)}
                          >
                            <span className="dati-ota__attention-dot" aria-hidden="true" />
                            {datiCopy.costs.attentionRow}
                          </Link>
                        ) : null}
                      </th>
                      <td>{formatMoneyCents(row.net_cost, costs.currency)}</td>
                      <td>
                        {row.cpor !== null ? (
                          formatMoneyCents(row.cpor, costs.currency)
                        ) : (
                          <span className="dati-na-text">{cporStatusText(row.cpor_status)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <DatiEmpty title={datiCopy.costs.emptyTitle} body={datiCopy.costs.emptyBody} />
          )}
        </DatiCard>

        {costs.decision !== null ? (
          <DatiCard id="dati-costs-decision" title={datiCopy.costs.decisionTitle} className="dati-decision-card">
            <p>
              {datiCopy.costs.decisionBody(
                formatMonthName(costs.decision.period_start),
                costCategoryLabel(costs.decision.category),
              )}
            </p>
            {costs.decision.actual_cpor !== null && costs.decision.expected_cpor !== null ? (
              <p className="dati-note">
                {datiCopy.costs.decisionFigures(
                  formatMoneyCents(costs.decision.actual_cpor, costs.decision.currency ?? costs.currency),
                  formatMoneyCents(costs.decision.expected_cpor, costs.decision.currency ?? costs.currency),
                )}
              </p>
            ) : null}
            <p className="dati-decision-card__link">
              <span className="dati-ota__attention-dot" aria-hidden="true" />
              <Link href={decisionDetailRoute(propertyId, costs.decision.decision_id)}>
                {datiCopy.costs.decisionLink}
              </Link>
            </p>
          </DatiCard>
        ) : null}
      </div>
    </div>
  );
}

// --- Personale --------------------------------------------------------------------------------------

export function DatiLaborPanel({ overview, propertyId, timeZone }: DatiPanelProps) {
  const { labor } = overview;
  const range = formatDateRange(labor.window_start, labor.window_end);
  const freshness = domainFreshnessLine(
    datiCopy.freshness.labor,
    overview.freshness.labor,
    overview.as_of_local_date,
    timeZone,
  );
  const state = overview.analysis.domain_states.find((item) => item.domain === "LABOR")?.state;
  const available = labor.state === "AVAILABLE" && labor.categories.length > 0;

  return (
    <div className="dati-grid dati-grid--labor">
      <div className="dati-cell dati-cell--summary">
        <DatiCard id="dati-labor-summary" title={datiCopy.labor.summaryTitle} className="dati-labor-summary">
          <p className="dati-note">{datiCopy.labor.basis(range)}</p>
          {labor.state === "AVAILABLE" ? (
            <p className="dati-labor-summary__days">{datiCopy.labor.daysWithData(labor.days_with_data)}</p>
          ) : (
            <DatiEmpty title={datiCopy.labor.emptyTitle} body={unavailableReasonText(labor.reason)} />
          )}
          <p className="dati-note">{datiCopy.labor.noRatioNote}</p>
          {state === "NOT_ANALYZED" ? <p className="dati-note">{datiCopy.labor.notAnalyzedNote}</p> : null}
          <DomainFacts overview={overview} domain="LABOR" freshness={freshness} />
        </DatiCard>
      </div>

      <div className="dati-cell dati-cell--list">
        <DatiCard id="dati-labor-categories" title={datiCopy.labor.categoriesTitle} className="dati-labor-table-card">
          {available ? (
            <div className="dati-table__scroll" role="region" aria-label={datiCopy.scrollable(datiCopy.labor.categoriesTitle)} tabIndex={0}>
              <table className="dati-table dati-table--categories">
                <caption className="visually-hidden">{datiCopy.labor.caption}</caption>
                <thead>
                  <tr>
                    <th scope="col">{datiCopy.labor.colCategory}</th>
                    <th scope="col">{datiCopy.labor.colHours}</th>
                    <th scope="col">{datiCopy.labor.colCost}</th>
                    <th scope="col">{datiCopy.labor.colDays}</th>
                  </tr>
                </thead>
                <tbody>
                  {labor.categories.map((row) => (
                    <tr key={row.category}>
                      <th scope="row">{laborCategoryLabel(row.category)}</th>
                      <td>{formatHours(row.planned_hours, 1)}</td>
                      <td>
                        {row.planned_cost !== null ? (
                          formatMoneyCents(row.planned_cost, labor.currency)
                        ) : (
                          <span className="dati-na" aria-label={datiCopy.table.noData}>
                            —
                          </span>
                        )}
                      </td>
                      <td>
                        {datiCopy.labor.daysComplete(row.days_complete)}
                        {row.days_incomplete > 0 ? (
                          <span className="dati-na-text"> · {datiCopy.labor.daysIncomplete(row.days_incomplete)}</span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <DatiEmpty title={datiCopy.labor.emptyTitle} body={datiCopy.labor.emptyBody} />
          )}
        </DatiCard>

        {labor.decision !== null ? (
          <DatiCard id="dati-labor-decision" title={datiCopy.labor.decisionTitle} className="dati-decision-card">
            <p>{laborCategoryLabel(labor.decision.category)}</p>
            {labor.decision.scheduled_hours !== null &&
            labor.decision.expected_hours !== null &&
            labor.decision.excess_hours !== null ? (
              <p className="dati-note">
                {datiCopy.labor.decisionFigures(
                  formatHours(labor.decision.scheduled_hours, 1),
                  formatHours(labor.decision.expected_hours, 1),
                  formatHours(labor.decision.excess_hours, 1),
                )}
              </p>
            ) : null}
            <p className="dati-decision-card__link">
              <span className="dati-ota__attention-dot" aria-hidden="true" />
              <Link href={decisionDetailRoute(propertyId, labor.decision.decision_id)}>
                {datiCopy.labor.decisionLink}
              </Link>
            </p>
          </DatiCard>
        ) : null}
      </div>
    </div>
  );
}
