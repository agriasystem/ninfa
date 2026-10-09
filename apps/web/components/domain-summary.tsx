import type { ComponentType, SVGProps } from "react";

import type { AnalysisDomain } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import type { DomainTile } from "@/lib/home/domain-summary";

import { BarsIcon, DatabaseIcon, NetworkIcon, UsersIcon } from "./icons";

const DOMAIN_ICONS: Record<AnalysisDomain, ComponentType<SVGProps<SVGSVGElement>>> = {
  REVENUE: BarsIcon,
  DISTRIBUTION: NetworkIcon,
  COSTS: DatabaseIcon,
  LABOR: UsersIcon,
};

export interface DomainSummaryProps {
  tiles: DomainTile[];
}

/**
 * The four-area strip (Home UI V1): Ricavi / Distribuzione / Costi / Personale. TEXTUAL status only
 * - ZERO analytical graphs - and the tiles are NOT links in V1 (no per-area destination exists).
 * One single attention colour for every area with something to look at (the backend exposes no
 * severity, so none is invented - D4); grey/hollow for "not analysed"/"not available". The
 * status is ALWAYS also written in words, so no information depends on colour.
 */
export function DomainSummary({ tiles }: DomainSummaryProps) {
  return (
    <ul className="domain-summary" aria-label={copy.home.domainSummaryLabel}>
      {tiles.map((tile) => {
        const DomainIcon = DOMAIN_ICONS[tile.domain];
        return (
          <li key={tile.domain} className="domain-tile" data-tone={tile.tone}>
            <span className="domain-tile__dot" aria-hidden="true" />
            <DomainIcon className="domain-tile__icon" />
            <span className="domain-tile__text">
              <span className="domain-tile__label">{tile.label}</span>
              <span className="domain-tile__status">{tile.text}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
