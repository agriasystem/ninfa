"use client";

import Link from "next/link";
import type { ComponentType, CSSProperties, SVGProps } from "react";

import type { AnalysisDomain } from "@ninfa/contracts";

import { analysisDomainLabels } from "@/lib/copy";
import { decisioniCopy } from "@/lib/decisions/list-copy";
import type { DecisionRowData, RowVisual } from "@/lib/decisions/list-view-model";

import { ArrowRightIcon, BarsIcon, DatabaseIcon, NetworkIcon, UsersIcon } from "./icons";

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

/** The four areas keep the icons the Home's area strip already uses. */
export const AREA_ICONS: Record<AnalysisDomain, IconComponent> = {
  REVENUE: BarsIcon,
  DISTRIBUTION: NetworkIcon,
  COSTS: DatabaseIcon,
  LABOR: UsersIcon,
};

/** How strongly the rank pill is drawn. It is a presentation of the engine's ORDER (1st, 2nd, later) - NINFA
 * has no severity, and nothing here is called Alta / Media / Bassa. */
export function rankTone(rank: number): "first" | "second" | "later" {
  if (rank <= 1) return "first";
  if (rank === 2) return "second";
  return "later";
}

/** `value` scaled to `max` as a percentage, never below a visible sliver for a real, non-zero value. */
function heightOf(value: number, max: number): string {
  if (max <= 0 || value <= 0) return "0%";
  return `${Math.max(6, Math.min(100, (value / max) * 100))}%`;
}

function Visual({ visual }: { visual: RowVisual }) {
  if (visual.kind === "share") {
    const share = Math.max(0, Math.min(100, visual.share));
    return (
      <span
        className="decision-row__donut"
        style={{ "--share": `${share}%` } as CSSProperties}
        aria-hidden="true"
      />
    );
  }
  const max = Math.max(visual.found, visual.expected);
  return (
    <span className="decision-row__pair" aria-hidden="true">
      <span className="decision-row__pair-col">
        <i className="decision-row__bar decision-row__bar--found" style={{ height: heightOf(visual.found, max) }} />
        <b>{decisioniCopy.found}</b>
      </span>
      <span className="decision-row__pair-col">
        <i className="decision-row__bar decision-row__bar--expected" style={{ height: heightOf(visual.expected, max) }} />
        <b>{decisioniCopy.expected}</b>
      </span>
    </span>
  );
}

export interface DecisionRowProps {
  row: DecisionRowData;
  /** The decision's own detail page, with the property context. */
  href: string;
}

/**
 * One decision as a scannable row (the approved mockup's card): the area and its priority, what is wrong
 * and why, the key metric against its expected level, the impact, and one clear action.
 *
 * Problem + evidence, never a recommendation. The row is an `<article>` named by its title; the only
 * interactive element is the "Apri dettaglio" link - its accessible name carries the title - and its
 * `::after` stretches over the card, so the whole row is clickable for a pointer while a keyboard or a
 * screen reader meets exactly one link. The mini visual is decorative (`aria-hidden`): every number it
 * draws is also written in text beside it.
 */
export function DecisionRow({ row, href }: DecisionRowProps) {
  const titleId = `decision-row-${row.decisionId}-title`;
  const AreaIcon = AREA_ICONS[row.area];
  const { metric, impact } = row;

  return (
    <article className="decision-row" data-area={row.area} aria-labelledby={titleId}>
      <div className="decision-row__main">
        <span className="decision-row__tile" aria-hidden="true">
          <AreaIcon className="decision-row__tile-icon" />
        </span>
        <div className="decision-row__text">
          <div className="decision-row__meta">
            <span className="decision-row__area">
              <span className="decision-row__area-dot" aria-hidden="true" />
              {analysisDomainLabels[row.area]}
            </span>
            <span className={`decision-row__rank decision-row__rank--${rankTone(row.rank)}`}>
              {decisioniCopy.rank(row.rank)}
            </span>
          </div>
          <h3 id={titleId} className="decision-row__title">
            {row.title}
          </h3>
          {row.description !== null ? <p className="decision-row__description">{row.description}</p> : null}
          {row.detectedOn !== null ? (
            <p className="decision-row__detected">{decisioniCopy.detectedOn(row.detectedOn)}</p>
          ) : null}
        </div>
      </div>

      <div className="decision-row__metric">
        <div className="decision-row__metric-text">
          <p className="decision-row__label">{metric.label}</p>
          <p className="decision-row__value">{metric.value ?? "—"}</p>
          {metric.caption !== null ? <p className="decision-row__caption">{metric.caption}</p> : null}
          {metric.delta !== null ? (
            <p className="decision-row__delta">
              <span className="decision-row__chip">{metric.delta.text}</span>
              <span className="decision-row__vs">{metric.delta.caption}</span>
            </p>
          ) : null}
        </div>
        {row.visual !== null ? <Visual visual={row.visual} /> : null}
      </div>

      <div className="decision-row__impact">
        {impact !== null ? (
          <>
            <p className="decision-row__label">{impact.label}</p>
            <p className="decision-row__value">{impact.value}</p>
            <p className="decision-row__caption">{impact.caption}</p>
          </>
        ) : null}
        {row.reliabilityPercent !== null ? (
          <p className="decision-row__reliability">{decisioniCopy.reliability(row.reliabilityPercent)}</p>
        ) : null}
      </div>

      <div className="decision-row__action">
        <Link className="decision-row__cta" href={href} aria-label={decisioniCopy.openNamed(row.title)}>
          <span>{decisioniCopy.open}</span>
          <ArrowRightIcon className="decision-row__cta-icon" />
        </Link>
      </div>
    </article>
  );
}
