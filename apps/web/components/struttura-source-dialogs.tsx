"use client";

import { useState, type ReactNode } from "react";

import type {
  DataSourceDomain,
  DataSourcesResponse,
  SourceCardKey,
  SourceMethod,
} from "@ninfa/contracts";

import { importaFileRoute } from "@/lib/routes";
import { sourcesCopy } from "@/lib/sources/copy";
import type { SourceCardView } from "@/lib/sources/view-model";

import { StrutturaInvoiceDialog } from "./struttura-invoice-dialog";
import { StrutturaManageDialog } from "./struttura-manage-dialog";
import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton, StrutturaLinkButton } from "./struttura-parts";
import { StrutturaTemplateButton } from "./struttura-template-button";

export type SourceDialog =
  | { kind: "connect"; card: SourceCardKey }
  | { kind: "wizard" }
  | { kind: "manage"; card: SourceCardKey; confirmRemove?: boolean }
  | { kind: "invoices" };

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
  ACCOUNTING: sourcesCopy.methods.costsRegister,
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

function Option({ option, children }: { option: Pick<OptionCopy, "title" | "body">; children: ReactNode }) {
  return (
    <div className="struttura-option">
      <div>
        <h3 className="struttura-option__title">{option.title}</h3>
        <p className="struttura-option__body">{option.body}</p>
      </div>
      <div className="struttura-option__actions">{children}</div>
    </div>
  );
}

/**
 * How a kind of data gets in: a file goes through the "Importa file" page, which works out what it is. These
 * dialogs only say so and lead there. Invoices (XML), which that page does not read, get their own dialog.
 */
function FileOptions({
  propertyId,
  domain,
  option,
  onInvoices,
}: {
  propertyId: string;
  domain: DataSourceDomain;
  option: OptionCopy;
  onInvoices: () => void;
}) {
  const link = (
    <StrutturaLinkButton variant={domain === "COSTS" ? "outline" : "primary"} href={importaFileRoute(propertyId)}>
      {option.cta}
    </StrutturaLinkButton>
  );
  if (domain === "COSTS") {
    return (
      <>
        <Option option={sourcesCopy.methods.invoicesXml}>
          <StrutturaButton variant="primary" onClick={onInvoices}>
            {sourcesCopy.methods.invoicesXml.cta}
          </StrutturaButton>
        </Option>
        <Option option={option}>{link}</Option>
      </>
    );
  }
  return (
    <Option option={option}>
      {link}
      <StrutturaTemplateButton propertyId={propertyId} domain={domain} />
    </Option>
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
 * and the invoice import. They offer ONLY what the backend says NINFA can really do (`capabilities`); automatic
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
  const [wizardKind, setWizardKind] = useState<"bookings" | "distribution" | "costs" | "labor" | null>(null);

  const close = () => {
    setWizardKind(null);
    setDialog(null);
  };

  /**
   * Goes to the import of an invoice. This creates NOTHING: the backend sets the source up (or switches the
   * removed one back on) only when the confirmed import succeeds, so choosing "Collega fonte" and then closing
   * the dialog leaves the card "Non configurato".
   */
  const openInvoices = () => setDialog({ kind: "invoices" });

  if (dialog === null) return null;

  // --- an invoice -------------------------------------------------------------------------------
  if (dialog.kind === "invoices") {
    return (
      <StrutturaInvoiceDialog propertyId={propertyId} onImported={() => void refresh()} onClose={close} />
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
        uploadHref={domain === "COSTS" ? null : importaFileRoute(propertyId)}
        onUpload={() => setDialog({ kind: "connect", card: dialog.card })}
        reviewHref={importaFileRoute(propertyId, domain ?? undefined)}
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
            <FileOptions
              propertyId={propertyId}
              domain={domain}
              option={FILE_OPTION_OF_CARD[dialog.card]}
              onInvoices={openInvoices}
            />
          ) : (
            <p className="struttura-flow__note">{sourcesCopy.dialog.unavailable}</p>
          )}
          {sources.automatic_integrations.length === 0 ? <ComingSoonOption /> : null}
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
  const several = owner?.several_sources === true;
  const available = canProvide(sources, domain, METHOD_OF_DOMAIN[domain]);
  const option: OptionCopy =
    wizardKind === "distribution"
      ? { title: kinds.bookings.title, body: sourcesCopy.methods.channelCsv.body, cta: sourcesCopy.methods.channelCsv.cta }
      : FILE_OPTION_OF_CARD[OWNER_OF_DOMAIN[domain]];

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
        {configured && !several ? <p className="struttura-flow__note">{sourcesCopy.wizard.alreadyHave}</p> : null}
        {several ? (
          // Created outside this page: NINFA does not pick one, so no file can be offered.
          <p className="struttura-flow__error" role="alert">
            {sourcesCopy.errors.alreadyConfigured}
          </p>
        ) : available ? (
          <FileOptions propertyId={propertyId} domain={domain} option={option} onInvoices={openInvoices} />
        ) : (
          <p className="struttura-flow__note">{sourcesCopy.dialog.unavailable}</p>
        )}
        {!configured && sources.automatic_integrations.length === 0 ? <ComingSoonOption /> : null}
        <div className="struttura-flow__actions">
          <StrutturaButton variant="outline" onClick={() => setWizardKind(null)}>
            {sourcesCopy.dialog.back}
          </StrutturaButton>
        </div>
      </div>
    </StrutturaModal>
  );
}
