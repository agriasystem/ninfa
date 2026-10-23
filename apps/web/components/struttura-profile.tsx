import type { ReactNode } from "react";

import Image from "next/image";

import { strutturaCopy } from "@/lib/structure/copy";
import { formatCurrencyLabel, formatMonthRange, formatTimeZoneLabel } from "@/lib/structure/format";
import type { StructureProfile } from "@/lib/structure/types";

import { BuildingIcon, StarIcon } from "./icons";
import { StrutturaSection } from "./struttura-parts";

const COPY = strutturaCopy.profile;
const NOT_CONFIGURED = strutturaCopy.notConfigured;
const STAR_SLOTS = 5;

interface FactProps {
  label: string;
  /** `null` = nothing has set it: the fact then reads "Non configurata" instead of a value. */
  value: ReactNode | null;
  /** "Non configurato" for a masculine label (Numero camere); "Non configurata" is the default. */
  empty?: string;
  name?: boolean;
}

function Fact({ label, value, empty = NOT_CONFIGURED.feminine, name = false }: FactProps) {
  const configured = value !== null;
  return (
    <div className={name ? "struttura-fact struttura-fact--name" : "struttura-fact"}>
      <dt>{label}</dt>
      <dd data-state={configured ? "configured" : "not-configured"}>{configured ? value : empty}</dd>
    </div>
  );
}

/** The star category: five slots, the earned ones lit, followed by the plain words ("4 stelle"). */
function Stars({ count }: { count: number }) {
  return (
    <span className="struttura-stars">
      <span className="struttura-stars__row" aria-hidden="true">
        {Array.from({ length: STAR_SLOTS }, (_, index) => (
          <StarIcon
            key={index}
            className="struttura-stars__star"
            data-earned={index < count ? "true" : "false"}
          />
        ))}
      </span>
      {COPY.stars(count)}
    </span>
  );
}

/** The structure's photo, or a neutral tile while it has none. Decorative (`alt=""`): the page names the
 * structure in text right beside it, and the image is a placeholder until real photos exist - there is no
 * image management here on purpose. */
function Photo({ src }: { src: string | null }) {
  return (
    <div className="struttura-profile__photo" data-empty={src === null ? "true" : "false"}>
      {src !== null ? (
        <Image src={src} alt="" width={205} height={143} unoptimized loading="eager" draggable={false} />
      ) : (
        <BuildingIcon className="struttura-profile__photo-empty" />
      )}
    </div>
  );
}

/** Block 1 - the general facts NINFA uses as operating context. Only the name and the timezone are known
 * for certain; every other fact reads "Non configurata" until something really sets it. */
export function StrutturaProfile({ profile }: { profile: StructureProfile }) {
  return (
    <StrutturaSection
      id="struttura-profile"
      Icon={BuildingIcon}
      title={COPY.title}
      description={COPY.description}
    >
      <div className="struttura-profile">
        <Photo src={profile.imageSrc} />
        <dl className="struttura-facts">
          <Fact label={COPY.name} value={profile.name} name />
          <Fact label={COPY.type} value={profile.type} />
          <Fact label={COPY.category} value={profile.stars === null ? null : <Stars count={profile.stars} />} />
          <Fact label={COPY.location} value={profile.location} />
        </dl>
        <dl className="struttura-facts struttura-facts--secondary">
          <Fact label={COPY.roomCount} value={profile.roomCount} empty={NOT_CONFIGURED.masculine} />
          <Fact label={COPY.timeZone} value={formatTimeZoneLabel(profile.timeZone)} />
          <Fact
            label={COPY.currency}
            value={profile.currency === null ? null : formatCurrencyLabel(profile.currency)}
          />
          <Fact
            label={COPY.mainSeason}
            value={profile.mainSeason === null ? null : formatMonthRange(profile.mainSeason)}
          />
        </dl>
      </div>
    </StrutturaSection>
  );
}
