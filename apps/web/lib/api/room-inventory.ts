import type { RoomInventoryResponse, RoomInventorySavedResponse } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

/**
 * How many rooms a property can sell. The page sends one number: the nights, the limits and the refresh of
 * the analysis that follows are all the backend's.
 */

function roomInventoryPath(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/room-inventory`;
}

export function getRoomInventory(
  propertyId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<RoomInventoryResponse>> {
  return apiRequest<RoomInventoryResponse>(roomInventoryPath(propertyId), { method: "GET" }, fetchImpl);
}

/**
 * `validFrom` ("YYYY-MM-DD") is the day the number starts to be true; missing, the backend takes the property's
 * own today. It travels only when the person chose another day, so a plain save sends what it always sent.
 */
export function saveRoomInventory(
  propertyId: string,
  roomsAvailable: number,
  validFrom?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<RoomInventorySavedResponse>> {
  return apiRequest<RoomInventorySavedResponse>(
    roomInventoryPath(propertyId),
    {
      method: "PUT",
      body:
        validFrom === undefined
          ? { rooms_available: roomsAvailable }
          : { rooms_available: roomsAvailable, valid_from: validFrom },
    },
    fetchImpl,
  );
}
