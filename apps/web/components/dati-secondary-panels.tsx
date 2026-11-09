"use client";

import Link from "next/link";

import type {
  AnalysisDomain,
  DataLaborEconomics,
  DataOverviewResponse,
  DataPeriod,
  DataPeriodMetrics,
} from "@ninfa/contracts";

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
import { Kpi } from "./dati-kpi-grid";
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
              <table className="dati-table">
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

/** "15,37 €/h": a rate is the backend's figure, formatted; `null` stays `null` for the KPI to say why. */
function hourly(amount: string | null, currency: string): string | null {
  return amount === null ? null : `${formatMoneyCents(amount, currency)}/h`;
}

/** The sentence under the labor figures: only figures the backend sent, and the same words each time. */
function laborSynthesis(economics: DataLaborEconomics, currency: string): string {
  const copy = datiCopy.labor.synthesis;
  if (economics.cost_to_revenue_pct !== null && economics.average_hourly_cost !== null) {
    return copy.complete(
      formatPercent(economics.cost_to_revenue_pct, 1),
      formatMoneyCents(economics.average_hourly_cost, currency),
    );
  }
  return economics.planned_cost !== null ? copy.hoursAndCosts : copy.noCost;
}

function NoFigure() {
  return (
    <span className="dati-na" aria-label={datiCopy.table.noData}>
      —
    </span>
  );
}

export function DatiLaborPanel({ overview, propertyId, timeZone }: DatiPanelProps) {
  const { labor } = overview;
  const { economics, currency } = { economics: labor.economics, currency: labor.currency };
  const copy = datiCopy.labor;
  const range = formatDateRange(labor.window_start, labor.window_end);
  const freshness = domainFreshnessLine(
    datiCopy.freshness.labor,
    overview.freshness.labor,
    overview.as_of_local_date,
    timeZone,
  );
  const state = overview.analysis.domain_states.find((item) => item.domain === "LABOR")?.state;
  const available = labor.state === "AVAILABLE" && labor.categories.length > 0;
  const revenueGap = economics.revenue_gap === null ? undefined : copy.revenueGap[economics.revenue_gap];
  const withIncidence = labor.categories.some((row) => row.revenue_incidence_pct !== null);

  return (
    <div className="dati-labor">
      <header className="dati-labor__header">
        <h2>{copy.heading}</h2>
        <p className="dati-note">{copy.subtitle}</p>
      </header>

      {available ? (
        <div className="dati-kpis dati-kpis--labor" role="group" aria-label={copy.kpiGroupLabel}>
          <Kpi
            id="dati-labor-hours"
            label={copy.kpi.hours}
            value={economics.planned_hours === null ? null : formatHours(economics.planned_hours, 1)}
            note={copy.kpi.hoursNote(range)}
            unavailableNote={copy.kpi.noHours}
            highlight
          />
          <Kpi
            id="dati-labor-cost"
            label={copy.kpi.cost}
            value={economics.planned_cost === null ? null : formatMoneyCents(economics.planned_cost, currency)}
            note={copy.kpi.samePeriod}
            unavailableNote={copy.kpi.noCost}
          />
          <Kpi
            id="dati-labor-hourly-cost"
            label={copy.kpi.hourlyCost}
            value={hourly(economics.average_hourly_cost, currency)}
            note={copy.kpi.hourlyCostNote}
            unavailableNote={copy.kpi.noCost}
          />
          <Kpi
            id="dati-labor-incidence"
            label={copy.kpi.incidence}
            value={economics.cost_to_revenue_pct === null ? null : formatPercent(economics.cost_to_revenue_pct, 1)}
            note={copy.kpi.incidenceNote}
            unavailableNote={revenueGap ?? copy.kpi.noCost}
          />
          <Kpi
            id="dati-labor-revenue-per-hour"
            label={copy.kpi.revenuePerHour}
            value={hourly(economics.revenue_per_hour, currency)}
            note={copy.kpi.revenuePerHourNote}
            unavailableNote={revenueGap}
          />
        </div>
      ) : null}

      <div className="dati-grid dati-grid--labor">
        <div className="dati-cell dati-cell--summary">
          <DatiCard id="dati-labor-summary" title={copy.hoursAndCostsTitle} className="dati-labor-summary">
            <p className="dati-note">{copy.basis(range)}</p>
            {available ? (
              <>
                <dl className="dati-labor__facts">
                  <div>
                    <dt>{copy.factHours}</dt>
                    <dd>
                      {economics.planned_hours === null ? <NoFigure /> : formatHours(economics.planned_hours, 1)}
                    </dd>
                  </div>
                  <div>
                    <dt>{copy.factCost}</dt>
                    <dd>
                      {economics.planned_cost === null ? (
                        <NoFigure />
                      ) : (
                        formatMoneyCents(economics.planned_cost, currency)
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>{copy.factHourlyCost}</dt>
                    <dd>{hourly(economics.average_hourly_cost, currency) ?? <NoFigure />}</dd>
                  </div>
                  <div>
                    <dt>{copy.factRevenue}</dt>
                    <dd>
                      {economics.reference_revenue === null ? (
                        <NoFigure />
                      ) : (
                        formatMoneyCents(economics.reference_revenue, currency)
                      )}
                    </dd>
                  </div>
                </dl>
                <p className="dati-labor-summary__days">{copy.daysWithData(labor.days_with_data)}</p>
                {economics.reference_revenue !== null &&
                economics.period_start !== null &&
                economics.period_end !== null ? (
                  <p className="dati-note">
                    {copy.revenueNote(formatDateRange(economics.period_start, economics.period_end))}
                  </p>
                ) : null}
                <section className="dati-labor__synthesis" aria-labelledby="dati-labor-synthesis">
                  <h3 id="dati-labor-synthesis">{copy.synthesisTitle}</h3>
                  <p>{laborSynthesis(economics, currency)}</p>
                </section>
              </>
            ) : (
              <DatiEmpty title={copy.emptyTitle} body={unavailableReasonText(labor.reason)} />
            )}
            {state === "NOT_ANALYZED" ? <p className="dati-note">{copy.notAnalyzedNote}</p> : null}
            <DomainFacts overview={overview} domain="LABOR" freshness={freshness} />
          </DatiCard>
        </div>

        <div className="dati-cell dati-cell--list">
          <DatiCard id="dati-labor-categories" title={copy.categoriesTitle} className="dati-labor-table-card">
            {available ? (
              <div
                className="dati-table__scroll"
                role="region"
                aria-label={datiCopy.scrollable(copy.categoriesTitle)}
                tabIndex={0}
              >
                <table className="dati-table dati-table--categories dati-table--labor">
                  <caption className="visually-hidden">{copy.caption}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{copy.colCategory}</th>
                      <th scope="col">{copy.colHours}</th>
                      <th scope="col">{copy.colCost}</th>
                      <th scope="col">{copy.colHourlyCost}</th>
                      <th scope="col">{copy.colShare}</th>
                      {withIncidence ? <th scope="col">{copy.colIncidence}</th> : null}
                      <th scope="col">{copy.colDays}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {labor.categories.map((row) => (
                      <tr key={row.category}>
                        <th scope="row">{laborCategoryLabel(row.category)}</th>
                        <td>{formatHours(row.planned_hours, 1)}</td>
                        <td>
                          {row.planned_cost !== null ? formatMoneyCents(row.planned_cost, currency) : <NoFigure />}
                        </td>
                        <td>{hourly(row.average_hourly_cost, currency) ?? <NoFigure />}</td>
                        <td>{row.cost_share_pct !== null ? formatPercent(row.cost_share_pct, 1) : <NoFigure />}</td>
                        {withIncidence ? (
                          <td>
                            {row.revenue_incidence_pct !== null ? (
                              formatPercent(row.revenue_incidence_pct, 1)
                            ) : (
                              <NoFigure />
                            )}
                          </td>
                        ) : null}
                        <td>
                          {copy.daysComplete(row.days_complete)}
                          {row.days_incomplete > 0 ? (
                            <span className="dati-na-text"> · {copy.daysIncomplete(row.days_incomplete)}</span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <DatiEmpty title={copy.emptyTitle} body={copy.emptyBody} />
            )}
          </DatiCard>

          {labor.decision !== null ? (
            <DatiCard id="dati-labor-decision" title={copy.decisionTitle} className="dati-decision-card">
              <p>{laborCategoryLabel(labor.decision.category)}</p>
              {labor.decision.scheduled_hours !== null &&
              labor.decision.expected_hours !== null &&
              labor.decision.excess_hours !== null ? (
                <p className="dati-note">
                  {copy.decisionFigures(
                    formatHours(labor.decision.scheduled_hours, 1),
                    formatHours(labor.decision.expected_hours, 1),
                    formatHours(labor.decision.excess_hours, 1),
                  )}
                </p>
              ) : null}
              <p className="dati-decision-card__link">
                <span className="dati-ota__attention-dot" aria-hidden="true" />
                <Link href={decisionDetailRoute(propertyId, labor.decision.decision_id)}>{copy.decisionLink}</Link>
              </p>
            </DatiCard>
          ) : null}
        </div>
      </div>
    </div>
  );
}
