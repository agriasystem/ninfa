"use client";

import { useMemo, useState, type ComponentType, type SVGProps } from "react";

import type { SourceCardKey } from "@ninfa/contracts";

import { datiRoute } from "@/lib/routes";
import { sourcesCopy } from "@/lib/sources/copy";
import { strutturaCopy } from "@/lib/structure/copy";
import { useDataSources } from "@/lib/sources/use-data-sources";
import {
  buildCardViews,
  nothingConfigured,
  type CardButton,
  type SourceCardView,
} from "@/lib/sources/view-model";

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
import { StrutturaSourceDialogs, type SourceDialog } from "./struttura-source-dialogs";
import { StrutturaSourceMenu } from "./struttura-source-menu";
import { StrutturaButton, StrutturaLinkButton, StrutturaSection } from "./struttura-parts";

const COPY = sourcesCopy;
const SECTION = strutturaCopy.sources;

/** A neutral glyph per category - never a vendor's logo. */
const CATEGORY_ICONS: Record<SourceCardKey, ComponentType<SVGProps<SVGSVGElement>>> = {
  PMS: LayoutIcon,
  CHANNEL_MANAGER: CloudIcon,
  OTA: NetworkIcon,
  ACCOUNTING: DocumentIcon,
  STAFF: UsersIcon,
};

/** The page an action that is a LINK (not a dialog) goes to: the Dati section already shows the real
 * bookings and channels, so nothing is duplicated here. */
function hrefOfAction(propertyId: string, view: SourceCardView, item: CardButton): string | undefined {
  if (item.action === "view-channels") return datiRoute(propertyId, { tab: "distribution" });
  if (item.action === "view") return datiRoute(propertyId, { tab: "bookings" });
  return undefined;
}

function SourceCard({
  view,
  propertyId,
  onAction,
}: {
  view: SourceCardView;
  propertyId: string;
  onAction: (view: SourceCardView, item: CardButton) => void;
}) {
  const Icon = CATEGORY_ICONS[view.key];
  const connected = view.pill.tone === "connected";

  const renderButton = (item: CardButton, variant: "outline" | "link") => {
    const href = hrefOfAction(propertyId, view, item);
    if (href !== undefined) {
      return (
        <StrutturaLinkButton variant="outline" href={href} ariaLabel={item.ariaLabel}>
          {item.label}
        </StrutturaLinkButton>
      );
    }
    return variant === "outline" ? (
      <StrutturaButton variant="outline" ariaLabel={item.ariaLabel} onClick={() => onAction(view, item)}>
        {item.label}
      </StrutturaButton>
    ) : (
      <button
        type="button"
        className="struttura-source__link"
        aria-label={item.ariaLabel}
        onClick={() => onAction(view, item)}
      >
        {item.label}
      </button>
    );
  };

  return (
    <li className="struttura-source" data-connection={view.state === "NOT_CONFIGURED" ? "not-connected" : "connected"} data-state={view.state}>
      <span className="struttura-source__icon" aria-hidden="true">
        <Icon />
      </span>
      <div className="struttura-source__body">
        <h3 className="struttura-source__name">{view.name}</h3>
        <p className="struttura-source__detail">{view.line}</p>
        <span className="struttura-pill" data-tone={view.pill.tone}>
          {connected ? <CheckCircleIcon className="struttura-pill__icon" /> : null}
          {view.pill.text}
        </span>
        {view.meta !== null ? (
          <p className="struttura-source__meta">
            <span>{view.meta.label}</span>
            <strong>{view.meta.value}</strong>
          </p>
        ) : null}
        {view.primary !== null || view.secondary !== null ? (
          <div className="struttura-source__actions">
            {view.primary !== null ? renderButton(view.primary, "outline") : null}
            {view.secondary !== null ? renderButton(view.secondary, "link") : null}
          </div>
        ) : null}
      </div>
      <div className="struttura-source__more">
        <StrutturaSourceMenu
          label={COPY.actions.menuLabel(view.name)}
          items={view.menu}
          hrefOf={(item) => hrefOfAction(propertyId, view, item)}
          onSelect={(item) => onAction(view, item)}
        />
      </div>
    </li>
  );
}

function SourcesSkeleton() {
  return (
    <div className="struttura-sources-skeleton" aria-busy="true">
      <p className="visually-hidden" role="status">
        {COPY.loading}
      </p>
      {[0, 1, 2, 3, 4].map((index) => (
        <div key={index} className="struttura-sources-skeleton__card" aria-hidden="true" />
      ))}
    </div>
  );
}

export interface StrutturaSourcesProps {
  propertyId: string;
  timeZone: string;
  /** The request itself answered "this property no longer exists": the caller re-resolves the selection. */
  onPropertyInvalid: () => void;
}

/**
 * Block 4 - where NINFA's data come from, and what the user can do about it. Every card says what the
 * BACKEND says (configured, received through another source, never imported...): while the answer is on its
 * way the block says so, and if it fails the block says that - it never shows "Non configurato" it has not
 * verified. Each card works: "Collega fonte", "Carica file", "Gestisci" and the "..." menu open real
 * dialogs that put a file into NINFA through the existing import services. Nothing here simulates an
 * integration: what does not exist yet is "Prossimamente".
 */
export function StrutturaSources({ propertyId, timeZone, onPropertyInvalid }: StrutturaSourcesProps) {
  const sources = useDataSources(propertyId, onPropertyInvalid);
  const [dialog, setDialog] = useState<SourceDialog | null>(null);
  // "Oggi alle 09:31" is measured against ONE instant for the whole block.
  const [now] = useState(() => new Date());

  const views = useMemo(
    () => (sources.data === null ? [] : buildCardViews(sources.data, { now, timeZone })),
    [sources.data, now, timeZone],
  );

  function handleAction(view: SourceCardView, item: CardButton) {
    switch (item.action) {
      case "connect":
      case "configure":
        setDialog({ kind: "connect", card: view.key });
        break;
      case "manage":
        setDialog({ kind: "manage", card: view.key });
        break;
      case "remove":
        setDialog({ kind: "manage", card: view.key, confirmRemove: true });
        break;
      case "upload":
        if (view.card.domain !== null && !view.card.several_sources) {
          setDialog({ kind: "import", domain: view.card.domain });
        }
        break;
      default:
        break; // "view" / "view-channels" are links: the browser follows them
    }
  }

  return (
    <StrutturaSection
      id="struttura-sources"
      Icon={DatabaseIcon}
      title={SECTION.title}
      description={SECTION.description}
      action={
        <StrutturaButton
          variant="primary"
          Icon={PlusIcon}
          disabled={sources.data === null}
          onClick={() => setDialog({ kind: "wizard" })}
        >
          {COPY.actions.connectNew}
        </StrutturaButton>
      }
    >
      {sources.status === "loading" ? <SourcesSkeleton /> : null}

      {sources.status === "error" ? (
        <div className="struttura-sources-error" role="alert">
          <p>{COPY.loadError}</p>
          <StrutturaButton variant="outline" onClick={() => void sources.refresh()}>
            {COPY.retry}
          </StrutturaButton>
        </div>
      ) : null}

      {sources.data !== null ? (
        <>
          <ul className="struttura-sources" aria-label={SECTION.listLabel}>
            {views.map((view) => (
              <SourceCard key={view.key} view={view} propertyId={propertyId} onAction={handleAction} />
            ))}
          </ul>
          {nothingConfigured(sources.data) ? (
            <p className="struttura-sources__intro">{COPY.sectionIntro}</p>
          ) : null}
          <StrutturaSourceDialogs
            propertyId={propertyId}
            timeZone={timeZone}
            sources={sources.data}
            views={views}
            dialog={dialog}
            setDialog={setDialog}
            refresh={sources.refresh}
          />
        </>
      ) : null}
    </StrutturaSection>
  );
}
