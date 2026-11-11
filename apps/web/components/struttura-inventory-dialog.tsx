"use client";

import { useId, useState, type FormEvent } from "react";

import type { RoomInventoryResponse, RoomInventorySavedResponse } from "@ninfa/contracts";

import { saveRoomInventory } from "@/lib/api/room-inventory";
import { formatDayMonthYear } from "@/lib/data/dates";
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

/** The day as the person typed it, if it is a real day within the backend's own limits (the property's
 * today, and the oldest day a save may be valid from). ISO dates sort as text, so there is no date arithmetic
 * here: the limits are the backend's. */
function validFromOf(text: string, earliest: string, latest: string): string | null {
  return /^\d{4}-\d{2}-\d{2}$/.test(text) && text >= earliest && text <= latest ? text : null;
}

export interface StrutturaInventoryDialogProps {
  propertyId: string;
  inventory: RoomInventoryResponse;
  onSaved: (saved: RoomInventorySavedResponse) => void;
  onClose: () => void;
}

/**
 * "Configura inventario" / "Modifica inventario": one number, the rooms the structure can sell, and the day it is
 * valid from (today unless the person says otherwise: a hotel that begins with last month's costs needs last
 * month's rooms too). The nights it is written on, the limits and what happens next are the backend's; the page
 * says only what the person needs to know: what was already analysed does not change, and a new analysis is made.
 */
export function StrutturaInventoryDialog({
  propertyId,
  inventory,
  onSaved,
  onClose,
}: StrutturaInventoryDialogProps) {
  const inputId = useId();
  const hintId = useId();
  const dateId = useId();
  const dateHintId = useId();
  const [text, setText] = useState(inventory.rooms_available?.toString() ?? "");
  const [validFrom, setValidFrom] = useState(inventory.today);
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
    const day = validFromOf(validFrom, inventory.earliest_valid_from, inventory.today);
    if (day === null) {
      setProblem(
        COPY.validFromRefused(
          formatDayMonthYear(inventory.earliest_valid_from),
          formatDayMonthYear(inventory.today),
        ),
      );
      return;
    }
    setProblem(null);
    setSaving(true);
    // a plain save (today) sends what it always sent
    const result =
      day === inventory.today
        ? await saveRoomInventory(propertyId, rooms)
        : await saveRoomInventory(propertyId, rooms, day);
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
            aria-describedby={validFrom === inventory.today ? hintId : undefined}
            aria-invalid={problem !== null}
            onChange={(event) => setText(event.target.value)}
          />
          {/* "from today on" only while the day is today: an earlier day says its own thing below */}
          {validFrom === inventory.today ? (
            <p id={hintId} className="struttura-flow__note">
              {COPY.fromToday}
            </p>
          ) : null}
        </div>
        <div className="struttura-inventory__field">
          <label htmlFor={dateId}>{COPY.validFromLabel}</label>
          <input
            id={dateId}
            className="struttura-inventory__input struttura-inventory__input--date"
            type="date"
            value={validFrom}
            min={inventory.earliest_valid_from}
            max={inventory.today}
            disabled={saving}
            aria-describedby={dateHintId}
            aria-invalid={problem !== null && validFromOf(validFrom, inventory.earliest_valid_from, inventory.today) === null}
            onChange={(event) => setValidFrom(event.target.value)}
          />
          <p id={dateHintId} className="struttura-flow__note">
            {validFrom !== inventory.today ? COPY.validFromPast : COPY.validFromToday}
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
