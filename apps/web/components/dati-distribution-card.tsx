"use client";

import Link from "next/link";

import type { DataChannelWeight, DataDistribution } from "@ninfa/contracts";

import {
  channelGroupLabel,
  datiCopy,
  otaInsufficientReasonsText,
  otaOutcomeText,
  unavailableReasonText,
} from "@/lib/data/copy";
import { formatDateRange } from "@/lib/data/dates";
import { formatPercent } from "@/lib/data/format";
import { decisionDetailRoute } from "@/lib/routes";

import { DatiCard, DatiEmpty } from "./dati-parts";

const COMPACT_CHANNELS = 4;

/** Width of a bar segment, as a percentage of the track. Pure geometry of a figure the backend sent. */
function widthOf(percent: string | null): string {
  const value = percent === null ? Number.NaN : Number.parseFloat(percent);
  if (!Number.isFinite(value)) return "0%";
  return `${Math.max(0, Math.min(100, value))}%`;
}

function ChannelRows({
  channels,
  limit,
}: {
  channels: readonly DataChannelWeight[];
  limit: number | null;
}) {
  const shown = limit === null ? channels : channels.slice(0, limit);
  const hidden = channels.length - shown.length;
  return (
    <>
      <ul className="dati-channels">
        {shown.map((channel) => (
          <li key={channel.name} className="dati-channel" data-group={channel.group.toLowerCase()}>
            <span className="dati-channel__name">{channel.name}</span>
            <span className="dati-channel__group">{channelGroupLabel(channel.group)}</span>
            <span className="dati-channel__track" aria-hidden="true">
              <span style={{ width: widthOf(channel.share_pct) }} />
            </span>
            <span className="dati-channel__share">{formatPercent(channel.share_pct)}</span>
            <span className="dati-channel__nights">
              {datiCopy.distribution.channelRoomNights(channel.room_nights)}
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 ? <p className="dati-channels__more">{datiCopy.distribution.moreChannels(hidden)}</p> : null}
    </>
  );
}

export interface DatiDistributionCardProps {
  distribution: DataDistribution;
  propertyId: string;
  /** `compact`: the Panoramica's small card. `full`: the Distribuzione tab (every channel, the
   * classification coverage and the explanation of the two metrics). */
  variant?: "compact" | "full";
}

/**
 * The OTA dependency of the next 30 nights: the OTA share against the direct share, NINFA's own
 * reference level, and the weight of each channel.
 *
 * The OTA share (over OTA + direct only) and a channel's weight (over ALL channels) are DIFFERENT
 * metrics and are drawn and worded as different things. The reference is NINFA's expected level for
 * the property - called "Riferimento NINFA", never a "target". The orange attention indicator appears
 * only when a real OTA decision exists, and links to it. No commission amount is shown: NINFA does not
 * know them.
 */
export function DatiDistributionCard({
  distribution,
  propertyId,
  variant = "compact",
}: DatiDistributionCardProps) {
  const full = variant === "full";
  const title = datiCopy.distribution.title;

  if (distribution.state !== "AVAILABLE") {
    const notAnalyzed = distribution.reason === "NOT_ANALYZED";
    return (
      <DatiCard id={`dati-distribution-${variant}`} title={title} className="dati-distribution">
        <DatiEmpty
          title={
            notAnalyzed ? datiCopy.distribution.notAnalyzedTitle : datiCopy.distribution.unavailableTitle
          }
          body={unavailableReasonText(distribution.reason)}
        />
      </DatiCard>
    );
  }

  const hasShares = distribution.ota_share_pct !== null && distribution.direct_share_pct !== null;
  const range =
    distribution.window_start !== null && distribution.window_end !== null
      ? formatDateRange(distribution.window_start, distribution.window_end)
      : null;
  const outcomeText = otaOutcomeText(distribution.outcome);
  const insufficientBecause =
    distribution.outcome === "INSUFFICIENT_DATA" && distribution.insufficient_reasons.length > 0
      ? datiCopy.distribution.insufficientBecause(
          otaInsufficientReasonsText(distribution.insufficient_reasons),
        )
      : null;
  const mix = distribution.channel_mix;
  const decisionHref =
    distribution.decision_id !== null
      ? decisionDetailRoute(propertyId, distribution.decision_id)
      : null;

  return (
    <DatiCard
      id={`dati-distribution-${variant}`}
      title={title}
      className={`dati-distribution dati-distribution--${variant}`}
      actions={range !== null ? <span className="dati-card__basis">{datiCopy.distribution.window(range)}</span> : undefined}
    >
      {hasShares ? (
        <>
          <div className="dati-ota__figures">
            <p className="dati-ota__figure">
              <span className="dati-ota__value">{formatPercent(distribution.ota_share_pct)}</span>
              <span className="dati-ota__label">{datiCopy.distribution.ota}</span>
            </p>
            <p className="dati-ota__figure dati-ota__figure--direct">
              <span className="dati-ota__value">{formatPercent(distribution.direct_share_pct)}</span>
              <span className="dati-ota__label">{datiCopy.distribution.direct}</span>
            </p>
          </div>
          <div className="dati-ota__bar" aria-hidden="true">
            <span className="dati-ota__bar-ota" style={{ width: widthOf(distribution.ota_share_pct) }} />
            {distribution.reference_ota_share_pct !== null ? (
              <span
                className="dati-ota__reference"
                style={{ left: widthOf(distribution.reference_ota_share_pct) }}
              />
            ) : null}
          </div>
          {distribution.reference_ota_share_pct !== null ? (
            <p className="dati-ota__reference-text">
              {datiCopy.distribution.reference(formatPercent(distribution.reference_ota_share_pct))}
            </p>
          ) : null}
        </>
      ) : null}

      {decisionHref !== null ? (
        <p className="dati-ota__attention">
          <span className="dati-ota__attention-dot" aria-hidden="true" />
          <Link href={decisionHref}>{datiCopy.distribution.attention}</Link>
        </p>
      ) : outcomeText !== null ? (
        <p className="dati-ota__outcome">
          {outcomeText}
          {insufficientBecause !== null ? ` ${insufficientBecause}` : ""}
        </p>
      ) : null}

      {full && distribution.classification_coverage_pct !== null ? (
        <p className="dati-ota__coverage">
          {datiCopy.distribution.coverageShare(formatPercent(distribution.classification_coverage_pct))}
        </p>
      ) : null}

      <div className="dati-ota__channels">
        <h3 className="dati-ota__channels-title">{datiCopy.distribution.channelsTitle}</h3>
        {mix !== null && mix.channels.length > 0 ? (
          <>
            <ChannelRows channels={mix.channels} limit={full ? null : COMPACT_CHANNELS} />
            {full ? <p className="dati-ota__note">{datiCopy.distribution.channelsNote}</p> : null}
          </>
        ) : (
          <p className="dati-ota__note">{datiCopy.distribution.channelsEmpty}</p>
        )}
      </div>
    </DatiCard>
  );
}
