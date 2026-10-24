"use client";

import type { DataOverviewResponse, DataPeriod } from "@ninfa/contracts";

import { analysisDomainLabels } from "@/lib/copy";
import { datiCopy, domainStateText } from "@/lib/data/copy";
import { domainFreshnessLine } from "@/lib/data/freshness";
import { formatBusinessDateItalian } from "@/lib/date/property-date";

import { DatiDistributionCard } from "./dati-distribution-card";
import { DatiKpiGrid } from "./dati-kpi-grid";
import { DatiNightsTable } from "./dati-nights-table";
import { DatiOccupancyCard } from "./dati-occupancy-card";
import { DatiOccupancyChart } from "./dati-occupancy-chart";

export interface DatiPanelProps {
  overview: DataOverviewResponse;
  propertyId: string;
  timeZone: string;
}

/**
 * Coverage, kept visible but discreet: which of the four areas the analysis looked at (a skipped one
 * is "Non analizzato", a partial run is "Analisi parziale", an unrecorded coverage is "Non
 * disponibile" - never read as clear), and the freshness of each domain's own data. When today has no
 * analysis yet, the date of the last completed one is stated as a fact.
 */
export function DatiCoverage({ overview, timeZone }: DatiPanelProps) {
  const { analysis } = overview;
  const businessDate = overview.as_of_local_date;
  const costs = domainFreshnessLine(datiCopy.freshness.costs, overview.freshness.costs, businessDate, timeZone);
  const labor = domainFreshnessLine(datiCopy.freshness.labor, overview.freshness.labor, businessDate, timeZone);
  const last = analysis.last_successful_analysis;

  return (
    <section className="dati-coverage" aria-label={datiCopy.coverage.title}>
      <h2 className="dati-coverage__title">{datiCopy.coverage.title}</h2>
      <ul className="dati-coverage__chips">
        {analysis.domain_states.map((item) => (
          <li key={item.domain} className="dati-chip" data-state={item.state.toLowerCase()}>
            <span className="dati-chip__mark" aria-hidden="true" />
            <span className="dati-chip__domain">{analysisDomainLabels[item.domain]}</span>{" "}
            <span className="dati-chip__state">{domainStateText(item.domain, item.state)}</span>
          </li>
        ))}
      </ul>
      <ul className="dati-coverage__facts">
        <li data-kind={costs.kind}>{costs.text}</li>
        <li data-kind={labor.kind}>{labor.text}</li>
        {analysis.feed_state === "NOT_PROCESSED" ? (
          <li>
            {last !== null
              ? datiCopy.coverage.lastAnalysis(formatBusinessDateItalian(last.as_of_local_date))
              : datiCopy.coverage.neverAnalyzed}
          </li>
        ) : null}
      </ul>
    </section>
  );
}

export interface DatiOverviewPanelProps extends DatiPanelProps {
  period: DataPeriod;
  busy: boolean;
  onSelectPeriod: (period: DataPeriod) => void;
}

/**
 * Panoramica: the reference's composition in NINFA's language - a large occupancy card on the left, the
 * 2x2 KPI block in the centre, the principal analytical chart on the right; then a compact OTA card
 * under the occupancy and the large detail table under the other two. The grid is defined in CSS
 * (`.dati-grid--overview`): three columns from 1440px, two, then one.
 */
export function DatiOverviewPanel({
  overview,
  propertyId,
  timeZone,
  period,
  busy,
  onSelectPeriod,
}: DatiOverviewPanelProps) {
  return (
    <>
      <div className="dati-grid dati-grid--overview" aria-busy={busy}>
        <div className="dati-cell dati-cell--occupancy">
          <DatiOccupancyCard
            overview={overview}
            timeZone={timeZone}
            period={period}
            busy={busy}
            onSelectPeriod={onSelectPeriod}
          />
        </div>
        <div className="dati-cell dati-cell--kpis">
          <DatiKpiGrid overview={overview} />
        </div>
        <div className="dati-cell dati-cell--chart">
          <DatiOccupancyChart overview={overview} />
        </div>
        <div className="dati-cell dati-cell--ota">
          <DatiDistributionCard distribution={overview.distribution} propertyId={propertyId} />
        </div>
        <div className="dati-cell dati-cell--table">
          <DatiNightsTable overview={overview} propertyId={propertyId} />
        </div>
      </div>
      <DatiCoverage overview={overview} propertyId={propertyId} timeZone={timeZone} />
    </>
  );
}
