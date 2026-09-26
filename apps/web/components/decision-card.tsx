import type { DecisionCardData, DecisionCardViewModel } from "@/lib/decisions/card-view-models";
import { formatCount, formatDecimal, formatHours, formatMoney, formatPercent } from "@/lib/decisions/format";
import { copy } from "@/lib/copy";

function PickupFacts({ card }: { card: Extract<DecisionCardViewModel, { kind: "PICKUP" }> }) {
  return (
    <dl className="decision-card__facts">
      <div>
        <dt>Data soggiorno</dt>
        <dd>{card.stayDate}</dd>
      </div>
      <div>
        <dt>Pickup rilevato</dt>
        <dd>{formatCount(card.actualPickup)}</dd>
      </div>
      <div>
        <dt>Pickup atteso</dt>
        <dd>{formatDecimal(card.expectedPickup)}</dd>
      </div>
      {card.deltaRooms !== null ? (
        <div>
          <dt>Scostamento</dt>
          <dd>{formatDecimal(card.deltaRooms)}</dd>
        </div>
      ) : null}
      {card.missingRooms !== null ? (
        <div>
          <dt>Camere mancanti</dt>
          <dd>{formatDecimal(card.missingRooms)}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function OccupancyFacts({ card }: { card: Extract<DecisionCardViewModel, { kind: "OCCUPANCY" }> }) {
  return (
    <dl className="decision-card__facts">
      <div>
        <dt>Data soggiorno</dt>
        <dd>{card.stayDate}</dd>
      </div>
      <div>
        <dt>Previsione camere</dt>
        <dd>{formatDecimal(card.forecastRooms)}</dd>
      </div>
      <div>
        <dt>Atteso a fine finestra</dt>
        <dd>{formatDecimal(card.expectedFinalRooms)}</dd>
      </div>
      {card.occupancyGapPp !== null ? (
        <div>
          <dt>Scarto occupazione</dt>
          <dd>{formatPercent(card.occupancyGapPp)}</dd>
        </div>
      ) : null}
      {card.roomShortfall !== null ? (
        <div>
          <dt>Scarto camere</dt>
          <dd>{formatDecimal(card.roomShortfall)}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function OtaFacts({ card }: { card: Extract<DecisionCardViewModel, { kind: "OTA" }> }) {
  return (
    <dl className="decision-card__facts">
      <div>
        <dt>Quota OTA</dt>
        <dd>{formatPercent(card.otaShare)}</dd>
      </div>
      <div>
        <dt>Quota attesa</dt>
        <dd>{formatPercent(card.expectedOtaShare)}</dd>
      </div>
      <div>
        <dt>Periodo osservato</dt>
        <dd>
          {card.windowStart} – {card.windowEnd}
        </dd>
      </div>
      {card.structuralCondition !== null ? (
        <div>
          <dt>Dipendenza strutturale</dt>
          <dd>{card.structuralCondition ? "Sì" : "No"}</dd>
        </div>
      ) : null}
      {card.risingCondition !== null ? (
        <div>
          <dt>In aumento</dt>
          <dd>{card.risingCondition ? "Sì" : "No"}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function CostFacts({ card }: { card: Extract<DecisionCardViewModel, { kind: "COST" }> }) {
  return (
    <dl className="decision-card__facts">
      <div>
        <dt>Categoria di costo</dt>
        <dd>{card.costCategory}</dd>
      </div>
      <div>
        <dt>Periodo</dt>
        <dd>{card.periodStart}</dd>
      </div>
      <div>
        <dt>Costo per camera</dt>
        <dd>{formatDecimal(card.actualCpor, 2)}</dd>
      </div>
      <div>
        <dt>Atteso</dt>
        <dd>{formatDecimal(card.expectedCpor, 2)}</dd>
      </div>
      {card.deltaCpor !== null ? (
        <div>
          <dt>Scostamento</dt>
          <dd>{formatDecimal(card.deltaCpor, 2)}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function LaborFacts({ card }: { card: Extract<DecisionCardViewModel, { kind: "LABOR" }> }) {
  return (
    <dl className="decision-card__facts">
      <div>
        <dt>Data</dt>
        <dd>{card.workDate}</dd>
      </div>
      <div>
        <dt>Reparto</dt>
        <dd>{card.laborCategory}</dd>
      </div>
      <div>
        <dt>Ore programmate</dt>
        <dd>{formatHours(card.scheduledHours)}</dd>
      </div>
      <div>
        <dt>Ore attese</dt>
        <dd>{formatHours(card.expectedHours)}</dd>
      </div>
      <div>
        <dt>Ore in eccesso</dt>
        <dd>{formatHours(card.excessHours)}</dd>
      </div>
    </dl>
  );
}

function FactsFor({ card }: { card: DecisionCardViewModel }) {
  switch (card.kind) {
    case "PICKUP":
      return <PickupFacts card={card} />;
    case "OCCUPANCY":
      return <OccupancyFacts card={card} />;
    case "OTA":
      return <OtaFacts card={card} />;
    case "COST":
      return <CostFacts card={card} />;
    case "LABOR":
      return <LaborFacts card={card} />;
  }
}

export interface DecisionCardProps {
  data: DecisionCardData;
}

/** Problem + evidence, never a recommendation: no "Abbassa il prezzo", no "Riduci il personale" -
 * the exact five facts adapters above are the ONLY thing this card knows how to render. */
export function DecisionCard({ data }: DecisionCardProps) {
  return (
    <article className="decision-card">
      <header className="decision-card__header">
        <span className="decision-card__rank" aria-label={`${copy.today.rankLabel} ${data.rank}`}>
          #{data.rank}
        </span>
        <h3 className="decision-card__title">{data.title}</h3>
      </header>

      <FactsFor card={data.card} />

      <footer className="decision-card__footer">
        {data.confidencePercent !== null ? (
          <span className="decision-card__confidence">
            {copy.today.reliabilityLabel} {data.confidencePercent}%
          </span>
        ) : null}
        {data.economicProxy ? (
          <span className="decision-card__proxy">
            {formatMoney(data.economicProxy.amount, data.economicProxy.currency)}
          </span>
        ) : null}
      </footer>
    </article>
  );
}
