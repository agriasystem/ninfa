"use client";

import { useEffect, useState } from "react";

import type { ImportFieldKey, SavedImportConfiguration } from "@ninfa/contracts";

import {
  forgetImportConfiguration,
  getImportConfiguration,
  removeDataSource,
} from "@/lib/api/data-sources";
import { formatPropertyLocalDateLongItalian } from "@/lib/date/property-date";
import { sourcesCopy } from "@/lib/sources/copy";
import type { SourceCardView } from "@/lib/sources/view-model";

import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.manage;
const CONFIG = sourcesCopy.manage.configuration;

type ConfigurationState =
  | { kind: "loading" }
  | { kind: "none" }
  | { kind: "error" }
  | { kind: "loaded"; configuration: SavedImportConfiguration };

function meaningOf(field: ImportFieldKey): string {
  return sourcesCopy.fields[field];
}

function valueOf(field: ImportFieldKey, value: string): string {
  const choices: Partial<Record<string, Record<string, string>>> = sourcesCopy.choices;
  return choices[field]?.[value] ?? value;
}

export interface StrutturaManageDialogProps {
  propertyId: string;
  timeZone: string;
  view: SourceCardView;
  /** Opens straight on "Rimuovere questa fonte?" (the "..." menu's "Rimuovi fonte"). */
  initialConfirm?: boolean;
  /** "Carica nuovo file": goes to the import of the source's own kind of data. */
  onUpload: () => void;
  /** "Modifica associazioni": the same import, started from the columns. */
  onEditColumns: () => void;
  /** The source was switched off (or is already gone): the cards are re-read from the backend. */
  onRemoved: () => void;
  onClose: () => void;
}

/**
 * "Gestisci": how the data of this source arrive, when they last did, the way to load a new file and the
 * way to remove the source. Removing asks first and says exactly what it does: the source stops receiving
 * data, and what NINFA already received stays.
 *
 * For a source that reads a file the hotel already had, it also shows "Configurazione import": what each
 * column of that file means, with the ways to look at it again or to forget it. Forgetting asks first and
 * touches nothing that was imported.
 */
export function StrutturaManageDialog({
  propertyId,
  timeZone,
  view,
  initialConfirm = false,
  onUpload,
  onEditColumns,
  onRemoved,
  onClose,
}: StrutturaManageDialogProps) {
  const [confirming, setConfirming] = useState(initialConfirm);
  const [forgetting, setForgetting] = useState<"idle" | "confirm" | "busy">("idle");
  const [removing, setRemoving] = useState(false);
  const [failed, setFailed] = useState(false);
  const [forgotten, setForgotten] = useState(false);
  const [configuration, setConfiguration] = useState<ConfigurationState>({ kind: "loading" });
  const sourceId = view.card.data_source_id;
  const canRemove = view.state === "CONFIGURED_FILE" && sourceId !== null;
  const canUpload = view.state === "CONFIGURED_FILE" && sourceId !== null;
  // Invoices arrive as XML straight from the accounting software: there are no columns to match.
  const hasConfiguration = canUpload && view.card.domain !== null && view.card.domain !== "COSTS";

  useEffect(() => {
    if (!hasConfiguration || sourceId === null) return;
    let current = true;
    void getImportConfiguration(propertyId, sourceId).then((result) => {
      if (!current) return;
      if (result.ok) setConfiguration({ kind: "loaded", configuration: result.data });
      else if (result.code === "DATA_SOURCE_NOT_FOUND") setConfiguration({ kind: "none" });
      else setConfiguration({ kind: "error" });
    });
    return () => {
      current = false;
    };
  }, [hasConfiguration, propertyId, sourceId]);

  async function handleRemove() {
    if (sourceId === null) return;
    setRemoving(true);
    setFailed(false);
    const result = await removeDataSource(propertyId, sourceId);
    setRemoving(false);
    // A source that is already gone ends the same way: the cards say what is true now.
    if (result.ok || result.code === "DATA_SOURCE_NOT_FOUND") {
      onRemoved();
      return;
    }
    setFailed(true);
  }

  async function handleForget() {
    if (sourceId === null) return;
    setForgetting("busy");
    setFailed(false);
    const result = await forgetImportConfiguration(propertyId, sourceId);
    if (result.ok || result.code === "DATA_SOURCE_NOT_FOUND") {
      setConfiguration({ kind: "none" });
      setForgotten(true);
      setForgetting("idle");
      return;
    }
    setFailed(true);
    setForgetting("confirm");
  }

  if (confirming) {
    return (
      <StrutturaModal title={COPY.removeTitle} dismissible={!removing} onClose={onClose}>
        <div className="struttura-flow">
          <p>{COPY.removeBody}</p>
          {failed ? (
            <p className="struttura-flow__error" role="alert">
              {sourcesCopy.problems.GENERIC}
            </p>
          ) : null}
          <div className="struttura-flow__actions">
            <StrutturaButton variant="outline" onClick={() => setConfirming(false)}>
              {sourcesCopy.dialog.cancel}
            </StrutturaButton>
            <StrutturaButton variant="primary" onClick={() => void handleRemove()}>
              {removing ? COPY.removing : COPY.removeConfirm}
            </StrutturaButton>
          </div>
        </div>
      </StrutturaModal>
    );
  }

  if (forgetting !== "idle") {
    return (
      <StrutturaModal title={CONFIG.forgetTitle} dismissible={forgetting !== "busy"} onClose={onClose}>
        <div className="struttura-flow">
          <p>{CONFIG.forgetBody}</p>
          {failed ? (
            <p className="struttura-flow__error" role="alert">
              {sourcesCopy.problems.GENERIC}
            </p>
          ) : null}
          <div className="struttura-flow__actions">
            <StrutturaButton variant="outline" onClick={() => setForgetting("idle")}>
              {sourcesCopy.dialog.cancel}
            </StrutturaButton>
            <StrutturaButton variant="primary" onClick={() => void handleForget()}>
              {forgetting === "busy" ? CONFIG.forgetting : CONFIG.forgetConfirm}
            </StrutturaButton>
          </div>
        </div>
      </StrutturaModal>
    );
  }

  return (
    <StrutturaModal title={COPY.title(view.name)} onClose={onClose}>
      <div className="struttura-flow">
        <dl className="struttura-manage__facts">
          <div>
            <dt>{COPY.method}</dt>
            <dd>{view.line}</dd>
          </div>
          {view.meta !== null ? (
            <div>
              <dt>{view.meta.label}</dt>
              <dd>{view.meta.value}</dd>
            </div>
          ) : null}
        </dl>

        {hasConfiguration ? (
          <section className="struttura-manage__configuration" aria-labelledby="struttura-config-title">
            <h3 id="struttura-config-title" className="struttura-flow__subtitle">
              {CONFIG.title}
            </h3>
            <p className="struttura-flow__note">{CONFIG.intro}</p>
            {configuration.kind === "loading" ? (
              <p className="struttura-flow__note" role="status">
                {CONFIG.loading}
              </p>
            ) : null}
            {configuration.kind === "error" ? (
              <p className="struttura-flow__error" role="alert">
                {CONFIG.loadError}
              </p>
            ) : null}
            {configuration.kind === "none" ? (
              <p className="struttura-flow__note">{forgotten ? CONFIG.forgotten : CONFIG.none}</p>
            ) : null}
            {configuration.kind === "loaded" ? (
              <>
                <ul className="struttura-manage__columns">
                  {configuration.configuration.columns.map((item) => (
                    <li key={item.field}>{CONFIG.columnLine(item.column, meaningOf(item.field))}</li>
                  ))}
                  {configuration.configuration.constants.map((item) => (
                    <li key={item.field}>
                      {CONFIG.fixedLine(meaningOf(item.field), valueOf(item.field, item.value))}
                    </li>
                  ))}
                </ul>
                <p className="struttura-flow__note">
                  {CONFIG.lastUsed}:{" "}
                  {configuration.configuration.last_used_at === null
                    ? CONFIG.never
                    : formatPropertyLocalDateLongItalian(
                        new Date(configuration.configuration.last_used_at),
                        timeZone,
                      )}
                </p>
                {!configuration.configuration.schema_current ? (
                  <p className="struttura-flow__note">{CONFIG.outdated}</p>
                ) : null}
                <div className="struttura-flow__actions">
                  <StrutturaButton variant="outline" onClick={onEditColumns}>
                    {CONFIG.edit}
                  </StrutturaButton>
                  <StrutturaButton variant="outline" onClick={() => setForgetting("confirm")}>
                    {CONFIG.forget}
                  </StrutturaButton>
                </div>
              </>
            ) : null}
          </section>
        ) : null}

        <div className="struttura-flow__actions">
          {canUpload ? (
            <StrutturaButton variant="primary" onClick={onUpload}>
              {sourcesCopy.actions.uploadNew}
            </StrutturaButton>
          ) : null}
          {canRemove ? (
            <StrutturaButton variant="outline" onClick={() => setConfirming(true)}>
              {sourcesCopy.actions.remove}
            </StrutturaButton>
          ) : null}
          <StrutturaButton variant="soft" onClick={onClose}>
            {sourcesCopy.dialog.close}
          </StrutturaButton>
        </div>
      </div>
    </StrutturaModal>
  );
}
