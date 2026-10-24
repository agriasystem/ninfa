import type { ComponentType, SVGProps } from "react";

import { strutturaCopy } from "@/lib/structure/copy";
import { formatMonthRange } from "@/lib/structure/format";
import type { OperatingParameters } from "@/lib/structure/types";

import { BarsIcon, CalendarIcon, PencilIcon, UsersIcon } from "./icons";
import { StrutturaButton, StrutturaSection, type StrutturaActions } from "./struttura-parts";

const COPY = strutturaCopy.parameters;
const NOT_CONFIGURED = strutturaCopy.notConfigured;

interface Tile {
  key: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  /** `null` = the parameter is not configured: the tile then reads "Non configurato/a" and has no detail. */
  value: { text: string; detail: string } | null;
  /** "Non configurato" for a masculine label (Periodo di apertura); "Non configurata" otherwise. */
  empty: string;
}

/** The three parameters the analysis reads. Nothing is added here on a whim: a parameter belongs on this
 * page only once an NINFA engine actually uses it. */
function tiles({ opening, peakSeason, maxGuests }: OperatingParameters): Tile[] {
  return [
    {
      key: "opening",
      Icon: CalendarIcon,
      label: COPY.opening,
      value:
        opening === null
          ? null
          : {
              text: opening.allYear ? COPY.openAllYear : COPY.openSeasonal,
              detail: COPY.annualClosure(
                opening.annualClosure === null ? COPY.noAnnualClosure : formatMonthRange(opening.annualClosure),
              ),
            },
      empty: NOT_CONFIGURED.masculine,
    },
    {
      key: "seasonality",
      Icon: BarsIcon,
      label: COPY.seasonality,
      value: peakSeason === null ? null : { text: COPY.peakSeason, detail: formatMonthRange(peakSeason) },
      empty: NOT_CONFIGURED.feminine,
    },
    {
      key: "capacity",
      Icon: UsersIcon,
      label: COPY.capacity,
      value: maxGuests === null ? null : { text: COPY.maxCapacity, detail: COPY.guests(maxGuests) },
      empty: NOT_CONFIGURED.feminine,
    },
  ];
}

/** Block 3 - the operating parameters that shape how the data is read. A parameter nothing has set reads
 * "Non configurato/a", never a default or an example value. */
export function StrutturaParameters({
  parameters,
  actions,
}: {
  parameters: OperatingParameters;
  actions: StrutturaActions;
}) {
  return (
    <StrutturaSection
      id="struttura-parameters"
      Icon={CalendarIcon}
      title={COPY.title}
      description={COPY.description}
      action={
        <StrutturaButton variant="soft" Icon={PencilIcon} onClick={actions.onEditParameters}>
          {COPY.edit}
        </StrutturaButton>
      }
    >
      <ul className="struttura-tiles">
        {tiles(parameters).map(({ key, Icon, label, value, empty }) => (
          <li key={key} className="struttura-tile">
            <span className="struttura-tile__icon" aria-hidden="true">
              <Icon />
            </span>
            <div className="struttura-tile__text">
              <p className="struttura-tile__label">{label}</p>
              <p
                className="struttura-tile__value"
                data-state={value === null ? "not-configured" : "configured"}
              >
                {value === null ? empty : value.text}
              </p>
              {value !== null ? <p className="struttura-tile__detail">{value.detail}</p> : null}
            </div>
          </li>
        ))}
      </ul>
    </StrutturaSection>
  );
}
