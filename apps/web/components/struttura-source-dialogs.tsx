"use client";

import { useState } from "react";

import type {
  DataSourceDomain,
  DataSourcesResponse,
  SourceCardKey,
  SourceMethod,
} from "@ninfa/contracts";

import { propertyLocalDate } from "@/lib/date/property-date";
import { sourcesCopy } from "@/lib/sources/copy";
import type { SourceCardView } from "@/lib/sources/view-model";

import { StrutturaImportDialog } from "./struttura-import-dialog";
import { StrutturaManageDialog } from "./struttura-manage-dialog";
import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton } from "./struttura-parts";

export type SourceDialog =
  | { kind: "connect"; card: SourceCardKey }
  | { kind: "wizard" }
  | { kind: "manage"; card: SourceCardKey; confirmRemove?: boolean }
  | { kind: "import"; domain: DataSourceDomain; mode?: "import" | "edit" };

/** The card that owns each kind of file source (a card is a presentation of a kind of data). */
const OWNER_OF_DOMAIN: Record<DataSourceDomain, SourceCardKey> = {
  BOOKINGS: "PMS",
  COSTS: "ACCOUNTING",
  LABOR: "STAFF",
};

/** The kind of data each card brings in; Channel Manager and OTA read it from the bookings. */
const DOMAIN_OF_CARD: Record<SourceCardKey, DataSourceDomain> = {
  PMS: "BOOKINGS",
  CHANNEL_MANAGER: "BOOKINGS",
  OTA: "BOOKINGS",
  ACCOUNTING: "COSTS",
  STAFF: "LABOR",
};

type OptionCopy = { title: string; body: string; cta: string };

/** How a card's data can be provided: the file option, in the card's own words. */
const FILE_OPTION_OF_CARD: Record<SourceCardKey, OptionCopy> = {
  PMS: sourcesCopy.methods.bookingsCsv,
  CHANNEL_MANAGER: sourcesCopy.methods.bookingsCsv,
  OTA: sourcesCopy.methods.channelCsv,
  ACCOUNTING: sourcesCopy.methods.invoicesXml,
  STAFF: sourcesCopy.methods.laborCsv,
};

function canProvide(sources: DataSourcesResponse, domain: DataSourceDomain, method: SourceMethod): boolean {
  return sources.capabilities.some((item) => item.domain === domain && item.methods.includes(method));
}

const METHOD_OF_DOMAIN: Record<DataSourceDomain, SourceMethod> = {
  BOOKINGS: "CSV",
  COSTS: "XML",
  LABOR: "CSV",
};

function FileOption({ option, onChoose }: { option: OptionCopy; onChoose: () => void }) {
  return (
    <div className="struttura-option">
      <div>
        <h3 className="struttura-option__title">{option.title}</h3>
        <p className="struttura-option__body">{option.body}</p>
      </div>
      <StrutturaButton variant="primary" onClick={onChoose}>
        {option.cta}
      </StrutturaButton>
    </div>
  );
}

/** Automatic integrations do not exist yet: said plainly, never clickable, never named. */
function ComingSoonOption() {
  return (
    <div className="struttura-option struttura-option--soon">
      <div>
        <h3 className="struttura-option__title">{sourcesCopy.dialog.automaticTitle}</h3>
        <p className="struttura-option__body">{sourcesCopy.dialog.automaticBody}</p>
      </div>
      <span className="struttura-badge">{sourcesCopy.dialog.comingSoon}</span>
    </div>
  );
}

export interface StrutturaSourceDialogsProps {
  propertyId: string;
  timeZone: string;
  sources: DataSourcesResponse;
  views: SourceCardView[];
  dialog: SourceDialog | null;
  setDialog: (dialog: SourceDialog | null) => void;
  /** Re-reads the five cards from the backend. */
  refresh: () => Promise<void>;
}

/**
 * Every dialog of "Fonti dati": the per-card "Collega fonte", the "Collega una nuova fonte" wizard, "Gestisci"
 * and the file import. They offer ONLY what the backend says NINFA can really do (`capabilities`); automatic
 * integrations are "Prossimamente" and can never be started.
 */
export function StrutturaSourceDialogs({
  propertyId,
  timeZone,
  sources,
  views,
  dialog,
  setDialog,
  refresh,
}: StrutturaSourceDialogsProps) {
  const [startError, setStartError] = useState<string | null>(null);
  const [wizardKind, setWizardKind] = useState<"bookings" | "distribution" | "costs" | "labor" | null>(null);

  const close = () => {
    setStartError(null);
    setWizardKind(null);
    setDialog(null);
  };

  /**
   * Goes to the import of a kind of data. This creates NOTHING: the backend sets the source up (or switches
   * the removed one back on) only when the confirmed import succeeds, so choosing "Collega fonte" and then
   * closing the dialog leaves the card "Non configurato".
   */
  function start(domain: DataSourceDomain) {
    const owner = sources.cards.find((card) => card.card === OWNER_OF_DOMAIN[domain]);
    if (owner?.several_sources) {
      setStartError(sourcesCopy.errors.alreadyConfigured);
      return;
    }
    setStartError(null);
    setDialog({ kind: "import", domain });
  }

  if (dialog === null) return null;

  // --- the file import ----------------------------------------------------------------------------
  if (dialog.kind === "import") {
    return (
      <StrutturaImportDialog
        propertyId={propertyId}
        timeZone={timeZone}
        domain={dialog.domain}
        mode={dialog.mode}
        snapshotLocalDate={propertyLocalDate(new Date(), timeZone)}
        onImported={() => void refresh()}
        onClose={close}
      />
    );
  }

  // --- "Gestisci" ---------------------------------------------------------------------------------
  if (dialog.kind === "manage") {
    const view = views.find((item) => item.key === dialog.card);
    if (view === undefined) return null;
    const domain = view.card.domain;
    return (
      <StrutturaManageDialog
        propertyId={propertyId}
        timeZone={timeZone}
        view={view}
        initialConfirm={dialog.confirmRemove === true}
        onUpload={() => {
          if (domain !== null) start(domain);
        }}
        onEditColumns={() => {
          if (domain !== null) setDialog({ kind: "import", domain, mode: "edit" });
        }}
        onRemoved={() => {
          close();
          void refresh();
        }}
        onClose={close}
      />
    );
  }

  // --- "Collega fonte" of one card ---------------------------------------------------------------------
  if (dialog.kind === "connect") {
    const copy = sourcesCopy.connect[dialog.card];
    const domain = DOMAIN_OF_CARD[dialog.card];
    const available = canProvide(sources, domain, METHOD_OF_DOMAIN[domain]);
    return (
      <StrutturaModal title={copy.title} description={copy.intro} onClose={close}>
        <div className="struttura-options">
          {available ? (
            <FileOption option={FILE_OPTION_OF_CARD[dialog.card]} onChoose={() => start(domain)} />
          ) : (
            <p className="struttura-flow__note">{sourcesCopy.dialog.unavailable}</p>
          )}
          {sources.automatic_integrations.length === 0 ? <ComingSoonOption /> : null}
          {startError !== null ? (
            <p className="struttura-flow__error" role="alert">
              {startError}
            </p>
          ) : null}
        </div>
      </StrutturaModal>
    );
  }

  // --- "Collega una nuova fonte": what data, then how ---------------------------------------------------
  const kinds = sourcesCopy.wizard.kinds;
  const kindToDomain: Record<NonNullable<typeof wizardKind>, DataSourceDomain> = {
    bookings: "BOOKINGS",
    distribution: "BOOKINGS",
    costs: "COSTS",
    labor: "LABOR",
  };

  if (wizardKind === null) {
    return (
      <StrutturaModal
        title={sourcesCopy.wizard.title}
        description={sourcesCopy.wizard.question}
        onClose={close}
      >
        <div className="struttura-options">
          {(["bookings", "distribution", "costs", "labor"] as const).map((kind) => (
            <button
              key={kind}
              type="button"
              className="struttura-kind"
              onClick={() => setWizardKind(kind)}
            >
              <span className="struttura-kind__title">{kinds[kind].title}</span>
              <span className="struttura-kind__body">{kinds[kind].body}</span>
            </button>
          ))}
        </div>
      </StrutturaModal>
    );
  }

  const domain = kindToDomain[wizardKind];
  const owner = sources.cards.find((card) => card.card === OWNER_OF_DOMAIN[domain]);
  const configured = owner !== undefined && owner.state !== "NOT_CONFIGURED";
  const available = canProvide(sources, domain, METHOD_OF_DOMAIN[domain]);
  const option: OptionCopy =
    wizardKind === "distribution"
      ? { title: kinds.bookings.title, body: sourcesCopy.methods.channelCsv.body, cta: sourcesCopy.methods.channelCsv.cta }
      : wizardKind === "bookings"
        ? sourcesCopy.methods.bookingsCsv
        : wizardKind === "costs"
          ? sourcesCopy.methods.invoicesXml
          : sourcesCopy.methods.laborCsv;

  return (
    <StrutturaModal
      title={kinds[wizardKind].title}
      description={sourcesCopy.wizard.howQuestion}
      onClose={close}
    >
      <div className="struttura-options">
        {wizardKind === "distribution" ? (
          <p className="struttura-flow__note">{sourcesCopy.wizard.distributionNote}</p>
        ) : null}
        {configured ? <p className="struttura-flow__note">{sourcesCopy.wizard.alreadyHave}</p> : null}
        {available ? (
          <FileOption
            option={
              configured
                ? { ...option, title: sourcesCopy.actions.uploadNew, cta: sourcesCopy.actions.uploadNew }
                : option
            }
            onChoose={() => start(domain)}
          />
        ) : (
          <p className="struttura-flow__note">{sourcesCopy.dialog.unavailable}</p>
        )}
        {!configured && sources.automatic_integrations.length === 0 ? <ComingSoonOption /> : null}
        {startError !== null ? (
          <p className="struttura-flow__error" role="alert">
            {startError}
          </p>
        ) : null}
        <div className="struttura-flow__actions">
          <StrutturaButton variant="outline" onClick={() => setWizardKind(null)}>
            {sourcesCopy.dialog.back}
          </StrutturaButton>
        </div>
      </div>
    </StrutturaModal>
  );
}
