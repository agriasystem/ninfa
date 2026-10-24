import { strutturaCopy } from "@/lib/structure/copy";
import { formatMaxOccupancy } from "@/lib/structure/format";
import type { RoomType } from "@/lib/structure/types";

import { BedIcon, PencilIcon, PlusIcon } from "./icons";
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

/** No room type is configured: the card says so and offers the one next step. It shows no table, no demo
 * type and no count - an inventory nobody has set up is not an inventory of zero rooms. */
function RoomsEmpty({ actions }: { actions: StrutturaActions }) {
  return (
    <div className="struttura-empty">
      <p className="struttura-empty__title">{COPY.emptyTitle}</p>
      <StrutturaButton variant="soft" Icon={PlusIcon} onClick={actions.onConfigureInventory}>
        {COPY.configure}
      </StrutturaButton>
    </div>
  );
}

/** Block 2 - the room types and their structural configuration. Only what describes the inventory:
 * no calendar, bookings, rates, availability or room assignment (that is a PMS, and NINFA is not one).
 * With no room type configured it is an empty state with "Configura inventario" instead; "Modifica
 * inventario" appears once there is an inventory to modify. */
export function StrutturaRooms({
  rooms,
  actions,
}: {
  rooms: RoomType[];
  actions: StrutturaActions;
}) {
  const configured = rooms.length > 0;
  return (
    <StrutturaSection
      id="struttura-rooms"
      Icon={BedIcon}
      title={COPY.title}
      description={COPY.description}
      action={
        configured ? (
          <StrutturaButton variant="soft" Icon={PencilIcon} onClick={actions.onEditInventory}>
            {COPY.edit}
          </StrutturaButton>
        ) : null
      }
    >
      {configured ? <RoomsTable rooms={rooms} actions={actions} /> : <RoomsEmpty actions={actions} />}
    </StrutturaSection>
  );
}
