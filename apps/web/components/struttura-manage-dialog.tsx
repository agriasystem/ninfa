"use client";

import { useState } from "react";

import { removeDataSource } from "@/lib/api/data-sources";
import { sourcesCopy } from "@/lib/sources/copy";
import type { SourceCardView } from "@/lib/sources/view-model";

import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.manage;

export interface StrutturaManageDialogProps {
  propertyId: string;
  view: SourceCardView;
  /** Opens straight on "Rimuovere questa fonte?" (the "..." menu's "Rimuovi fonte"). */
  initialConfirm?: boolean;
  /** "Carica nuovo file": goes to the import of the source's own kind of data. */
  onUpload: () => void;
  /** The source was switched off (or is already gone): the cards are re-read from the backend. */
  onRemoved: () => void;
  onClose: () => void;
}

/**
 * "Gestisci": how the data of this source arrive, when they last did, the way to load a new file and the
 * way to remove the source. Removing asks first and says exactly what it does: the source stops receiving
 * data, and what NINFA already received stays.
 */
export function StrutturaManageDialog({
  propertyId,
  view,
  initialConfirm = false,
  onUpload,
  onRemoved,
  onClose,
}: StrutturaManageDialogProps) {
  const [confirming, setConfirming] = useState(initialConfirm);
  const [removing, setRemoving] = useState(false);
  const [failed, setFailed] = useState(false);
  const sourceId = view.card.data_source_id;
  const canRemove = view.state === "CONFIGURED_FILE" && sourceId !== null;
  const canUpload = view.state === "CONFIGURED_FILE" && sourceId !== null;

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
