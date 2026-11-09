"use client";

import { useState } from "react";

import Link from "next/link";

import type { RoomInventorySavedResponse } from "@ninfa/contracts";

import { useAnalysisStatus } from "@/lib/analysis/use-analysis-status";
import { datiRoute } from "@/lib/routes";
import { strutturaCopy } from "@/lib/structure/copy";
import { formatMaxOccupancy } from "@/lib/structure/format";
import type { RoomType } from "@/lib/structure/types";
import type { RoomInventoryState } from "@/lib/structure/use-room-inventory";

import { BedIcon, PencilIcon, PlusIcon } from "./icons";
import { StrutturaInventoryDialog } from "./struttura-inventory-dialog";
import {
  StrutturaButton,
  StrutturaMoreButton,
  StrutturaSection,
  type StrutturaActions,
} from "./struttura-parts";

const COPY = strutturaCopy.rooms;

function RoomStatus({ status }: { status: RoomType["status"] }) {
  const active = status === "ACTIVE";
  return (
    <span className="struttura-status" data-status={active ? "active" : "inactive"}>
      <span className="struttura-status__dot" aria-hidden="true" />
      {active ? COPY.statusActive : COPY.statusInactive}
    </span>
  );
}

function RoomsTable({ rooms, actions }: { rooms: RoomType[]; actions: StrutturaActions }) {
  return (
    <div className="struttura-table-scroll" role="region" aria-label={COPY.scrollLabel} tabIndex={0}>
      <table className="struttura-table" aria-label={COPY.tableLabel}>
        <colgroup>
          <col className="struttura-table__col-type" />
          <col className="struttura-table__col-code" />
          <col className="struttura-table__col-rooms" />
          <col className="struttura-table__col-occupancy" />
          <col className="struttura-table__col-status" />
          <col className="struttura-table__col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">{COPY.columns.type}</th>
            <th scope="col">{COPY.columns.code}</th>
            <th scope="col">{COPY.columns.rooms}</th>
            <th scope="col">{COPY.columns.maxOccupancy}</th>
            <th scope="col">{COPY.columns.status}</th>
            <th scope="col">
              <span className="visually-hidden">{COPY.columns.actions}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rooms.map((room) => (
            <tr key={room.id}>
              <th scope="row">{room.name}</th>
              <td>{room.code}</td>
              <td>{room.rooms}</td>
              <td>{formatMaxOccupancy(room)}</td>
              <td>
                <RoomStatus status={room.status} />
              </td>
              <td className="struttura-table__actions">
                <StrutturaMoreButton
                  label={COPY.rowActions(room.name)}
                  onClick={actions.onRoomMenu ? () => actions.onRoomMenu?.(room.id) : undefined}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What happened after "Salva", in the backend's words: the refresh is the same one an import asks for, and
 * this only follows it. The person does not have to do anything, and the page says so. */
function SavedNote({ propertyId, saved }: { propertyId: string; saved: RoomInventorySavedResponse }) {
  const { status } = useAnalysisStatus({ propertyId });
  const line = !saved.analysis_requested
    ? saved.changed_nights === 0
      ? COPY.savedUnchanged
      : COPY.savedNoAnalysis
    : status === null || status.state === "IN_PROGRESS"
      ? COPY.analysisInProgress
      : status.state === "DELAYED"
        ? COPY.analysisDelayed
        : status.state === "FAILED"
          ? COPY.analysisFailed
          : COPY.analysisDone;
  return (
    <p className="struttura-inventory__saved" role="status">
      <span className="struttura-inventory__saved-title">{COPY.savedTitle(saved.rooms_available ?? 0)}</span>{" "}
      {line}{" "}
      <Link className="struttura-inventory__link" href={datiRoute(propertyId)}>
        {COPY.seeData}
      </Link>
    </p>
  );
}

/** Block 2 - how many rooms the structure can sell, the one thing NINFA needs to calculate the occupancy. Only
 * what describes the inventory: no calendar, bookings, rates, availability or room assignment (that is a PMS,
 * and NINFA is not one). Nothing configured is an empty state with "Configura inventario", never an inventory
 * of zero rooms; "Modifica inventario" appears once there is one to modify.
 *
 * `rooms` is the explicit demo fixture's table of room types (development and tests only). The real route has
 * none: there, the block reads and writes the real number through `inventory`. */
export function StrutturaRooms({
  propertyId,
  rooms,
  inventory,
  actions,
  onInventorySaved,
}: {
  propertyId: string;
  rooms: RoomType[];
  inventory: RoomInventoryState;
  actions: StrutturaActions;
  onInventorySaved: (saved: RoomInventorySavedResponse) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState<RoomInventorySavedResponse | null>(null);

  if (rooms.length > 0) {
    return (
      <StrutturaSection
        id="struttura-rooms"
        Icon={BedIcon}
        title={COPY.title}
        description={COPY.description}
        action={
          <StrutturaButton variant="soft" Icon={PencilIcon} onClick={actions.onEditInventory}>
            {COPY.edit}
          </StrutturaButton>
        }
      >
        <RoomsTable rooms={rooms} actions={actions} />
      </StrutturaSection>
    );
  }

  const known = inventory.kind === "loaded" ? inventory.inventory : null;
  const configured = known !== null && known.configured;
  return (
    <StrutturaSection
      id="struttura-rooms"
      Icon={BedIcon}
      title={COPY.title}
      description={COPY.description}
      action={
        configured ? (
          <StrutturaButton variant="soft" Icon={PencilIcon} onClick={() => setEditing(true)}>
            {COPY.edit}
          </StrutturaButton>
        ) : null
      }
    >
      {inventory.kind === "loading" ? <p className="struttura-flow__note">{COPY.loading}</p> : null}
      {inventory.kind === "error" ? (
        <p className="struttura-flow__error" role="alert">
          {COPY.loadError}
        </p>
      ) : null}
      {known !== null && !configured ? (
        <div className="struttura-empty">
          <p className="struttura-empty__title">{COPY.emptyTitle}</p>
          <StrutturaButton variant="soft" Icon={PlusIcon} onClick={() => setEditing(true)}>
            {COPY.configure}
          </StrutturaButton>
        </div>
      ) : null}
      {configured && known !== null ? (
        <div className="struttura-inventory">
          <p className="struttura-inventory__figure">
            <span className="struttura-inventory__label">{COPY.availableLabel}</span>
            <span className="struttura-inventory__value">{COPY.available(known.rooms_available ?? 0)}</span>
          </p>
          <p className="struttura-flow__note">{known.varies ? COPY.varies : COPY.fromToday}</p>
        </div>
      ) : null}
      {saved !== null ? <SavedNote propertyId={propertyId} saved={saved} /> : null}
      {editing && known !== null ? (
        <StrutturaInventoryDialog
          propertyId={propertyId}
          inventory={known}
          onSaved={(result) => {
            setEditing(false);
            setSaved(result);
            onInventorySaved(result);
          }}
          onClose={() => setEditing(false)}
        />
      ) : null}
    </StrutturaSection>
  );
}
