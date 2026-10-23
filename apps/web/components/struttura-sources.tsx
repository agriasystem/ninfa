import type { ComponentType, SVGProps } from "react";

import { strutturaCopy } from "@/lib/structure/copy";
import { formatUpdateAge } from "@/lib/structure/format";
import type { DataSource, DataSourceCategory } from "@/lib/structure/types";

import {
  CheckCircleIcon,
  CloudIcon,
  DatabaseIcon,
  DocumentIcon,
  LayoutIcon,
  NetworkIcon,
  PlusIcon,
  UsersIcon,
} from "./icons";
import {
  StrutturaButton,
  StrutturaMoreButton,
  StrutturaSection,
  type StrutturaActions,
} from "./struttura-parts";

const COPY = strutturaCopy.sources;

/** A neutral glyph per category - never a vendor's logo. */
const CATEGORY_ICONS: Record<DataSourceCategory, ComponentType<SVGProps<SVGSVGElement>>> = {
  PMS: LayoutIcon,
  CHANNEL_MANAGER: CloudIcon,
  OTA: NetworkIcon,
  ACCOUNTING: DocumentIcon,
  STAFF: UsersIcon,
};

function SourceCard({
  source,
  now,
  actions,
}: {
  source: DataSource;
  now: Date;
  actions: StrutturaActions;
}) {
  const label = strutturaCopy.categoryLabels[source.category];
  const Icon = CATEGORY_ICONS[source.category];
  const { connection } = source;
  const connected = connection.status === "CONNECTED";

  return (
    <li className="struttura-source" data-connection={connected ? "connected" : "not-connected"}>
      <span className="struttura-source__icon" aria-hidden="true">
        <Icon />
      </span>
      <div className="struttura-source__body">
        <h3 className="struttura-source__name">{label}</h3>
        {/* the line under the name: the system's name when one is really connected, otherwise the plain fact
            that none is - the same for every category, never a vendor on a source that is not wired */}
        <p className="struttura-source__detail">
          {connection.status === "CONNECTED" ? connection.provider : COPY.noSource}
        </p>
        <span className="struttura-pill" data-tone={connected ? "connected" : "idle"}>
          {connected ? <CheckCircleIcon className="struttura-pill__icon" /> : null}
          {connected ? COPY.connected : COPY.notConnected}
        </span>
        {connection.status === "CONNECTED" ? (
          <p className="struttura-source__meta">
            <span>{COPY.lastUpdate}</span>
            <strong>{formatUpdateAge(connection.lastUpdateAt, now)}</strong>
          </p>
        ) : (
          <StrutturaButton
            variant="outline"
            ariaLabel={`${COPY.connect} ${label}`}
            onClick={actions.onConnectSource ? () => actions.onConnectSource?.(source.category) : undefined}
          >
            {COPY.connect}
          </StrutturaButton>
        )}
      </div>
      <StrutturaMoreButton
        className="struttura-source__more"
        label={COPY.actions(label)}
        onClick={actions.onSourceMenu ? () => actions.onSourceMenu?.(source.category) : undefined}
      />
    </li>
  );
}

/** Block 4 - which systems feed NINFA. It states only WHETHER a system is connected and when it last
 * delivered something; how good, how far back and how complete the data is belongs to the Dati section.
 * It shows exactly what it is given: a source reads "Collegato" only when the data says so. */
export function StrutturaSources({
  sources,
  now,
  actions,
}: {
  sources: DataSource[];
  now: Date;
  actions: StrutturaActions;
}) {
  return (
    <StrutturaSection
      id="struttura-sources"
      Icon={DatabaseIcon}
      title={COPY.title}
      description={COPY.description}
      action={
        <StrutturaButton
          variant="primary"
          Icon={PlusIcon}
          onClick={actions.onConnectSource ? () => actions.onConnectSource?.() : undefined}
        >
          {COPY.connectNew}
        </StrutturaButton>
      }
    >
      <ul className="struttura-sources" aria-label={COPY.listLabel}>
        {sources.map((source) => (
          <SourceCard key={source.category} source={source} now={now} actions={actions} />
        ))}
      </ul>
    </StrutturaSection>
  );
}
