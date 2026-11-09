"use client";

import { useId, useState, type FormEvent } from "react";

import type { RoomInventoryResponse, RoomInventorySavedResponse } from "@ninfa/contracts";

import { saveRoomInventory } from "@/lib/api/room-inventory";
import { strutturaCopy } from "@/lib/structure/copy";

import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton } from "./struttura-parts";

const COPY = strutturaCopy.rooms.form;

/** The number as the person typed it, if it is a whole number within the backend's own limits. */
function roomsFrom(text: string, min: number, max: number): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const rooms = Number(trimmed);
  return rooms >= min && rooms <= max ? rooms : null;
}

export interface StrutturaInventoryDialogProps {
  propertyId: string;
  inventory: RoomInventoryResponse;
  onSaved: (saved: RoomInventorySavedResponse) => void;
  onClose: () => void;
}

/**
 * "Configura inventario" / "Modifica inventario": one number, the rooms the structure can sell. The nights it
 * is written on, the limits and what happens next are the backend's; the page says only what the person needs
 * to know: it counts from today, and what was already analysed does not change.
 */
export function StrutturaInventoryDialog({
  propertyId,
  inventory,
  onSaved,
  onClose,
}: StrutturaInventoryDialogProps) {
  const inputId = useId();
  const hintId = useId();
  const [text, setText] = useState(inventory.rooms_available?.toString() ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const limits = COPY.limits(inventory.min_rooms, inventory.max_rooms);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const rooms = roomsFrom(text, inventory.min_rooms, inventory.max_rooms);
    if (rooms === null) {
      setProblem(limits);
      return;
    }
    setProblem(null);
    setSaving(true);
    const result = await saveRoomInventory(propertyId, rooms);
    setSaving(false);
    if (result.ok) {
      onSaved(result.data);
      return;
    }
    setProblem(result.status === 422 ? limits : COPY.saveError);
  }

  return (
    <StrutturaModal
      title={inventory.configured ? COPY.titleEdit : COPY.titleConfigure}
      description={COPY.intro}
      dismissible={!saving}
      onClose={onClose}
    >
      <form className="struttura-flow" onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="struttura-inventory__field">
          <label htmlFor={inputId}>{COPY.label}</label>
          <input
            id={inputId}
            className="struttura-inventory__input"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={text}
            disabled={saving}
            aria-describedby={hintId}
            aria-invalid={problem !== null}
            onChange={(event) => setText(event.target.value)}
          />
          <p id={hintId} className="struttura-flow__note">
            {COPY.fromToday}
          </p>
        </div>
        {inventory.varies ? <p className="struttura-flow__note">{COPY.variesWarning}</p> : null}
        {problem !== null ? (
          <p className="struttura-flow__error" role="alert">
            {problem}
          </p>
        ) : null}
        <div className="struttura-flow__actions">
          <StrutturaButton variant="outline" disabled={saving} onClick={onClose}>
            {COPY.cancel}
          </StrutturaButton>
          <button type="submit" className="struttura-button struttura-button--primary" disabled={saving}>
            {saving ? COPY.saving : COPY.save}
          </button>
        </div>
      </form>
    </StrutturaModal>
  );
}
