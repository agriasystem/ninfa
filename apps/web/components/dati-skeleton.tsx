"use client";

import { datiCopy } from "@/lib/data/copy";

/**
 * The loading state: skeleton cards in the SAME grid as the final Panoramica (a large card, the 2x2
 * block, the chart, a compact card, the table), so nothing jumps when the data arrives and the page is
 * never replaced by a spinner. Purely decorative: the region announces one polite "loading" message.
 */
export function DatiSkeleton() {
  return (
    <div className="dati-grid dati-grid--overview dati-skeleton" aria-busy="true">
      <p className="visually-hidden" role="status">
        {datiCopy.loading}
      </p>
      <div className="dati-cell dati-cell--occupancy" aria-hidden="true">
        <div className="dati-card dati-skeleton__card dati-skeleton__card--tall" />
      </div>
      <div className="dati-cell dati-cell--kpis" aria-hidden="true">
        <div className="dati-kpis">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="dati-card dati-skeleton__card" />
          ))}
        </div>
      </div>
      <div className="dati-cell dati-cell--chart" aria-hidden="true">
        <div className="dati-card dati-skeleton__card dati-skeleton__card--tall" />
      </div>
      <div className="dati-cell dati-cell--ota" aria-hidden="true">
        <div className="dati-card dati-skeleton__card dati-skeleton__card--medium" />
      </div>
      <div className="dati-cell dati-cell--table" aria-hidden="true">
        <div className="dati-card dati-skeleton__card dati-skeleton__card--medium" />
      </div>
    </div>
  );
}
