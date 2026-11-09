"use client";

import { useCallback, useEffect, useState } from "react";

import type { RoomInventoryResponse } from "@ninfa/contracts";

import { getRoomInventory } from "@/lib/api/room-inventory";

export type RoomInventoryState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "loaded"; inventory: RoomInventoryResponse };

/** GET .../room-inventory for the property on screen. `accept` puts in the answer a save has just given. */
export function useRoomInventory(propertyId: string): {
  state: RoomInventoryState;
  accept: (inventory: RoomInventoryResponse) => void;
} {
  const [held, setHeld] = useState<{ propertyId: string; state: RoomInventoryState } | null>(null);

  useEffect(() => {
    let current = true;
    void getRoomInventory(propertyId).then((result) => {
      if (!current) return;
      setHeld({
        propertyId,
        state: result.ok ? { kind: "loaded", inventory: result.data } : { kind: "error" },
      });
    });
    return () => {
      current = false;
    };
  }, [propertyId]);

  const accept = useCallback(
    (inventory: RoomInventoryResponse) => setHeld({ propertyId, state: { kind: "loaded", inventory } }),
    [propertyId],
  );

  return {
    state: held !== null && held.propertyId === propertyId ? held.state : { kind: "loading" },
    accept,
  };
}
