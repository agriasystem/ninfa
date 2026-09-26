import { describe, expect, it } from "vitest";

import type { FeedItemResponse } from "@ninfa/contracts";

import { buildDecisionCardData } from "./card-view-models";

function priority(rank: number, confidenceScore: string) {
  return {
    rank,
    impact_score: "10",
    urgency_score: "10",
    confidence_score: confidenceScore,
    actionability_score: "10",
    priority_score: "10",
    candidate_fingerprint: "fp",
  };
}

function baseItem(overrides: Partial<FeedItemResponse>): FeedItemResponse {
  return {
    decision_id: "dec-1",
    decision_type: "REV_PICKUP_LOW",
    lifecycle_status: "OPEN",
    transition: "OPENED",
    priority: priority(1, "0.8234"),
    first_seen_local_date: "2026-09-20",
    last_seen_local_date: "2026-09-26",
    episode_count: 1,
    target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
    reason_codes: ["TRIGGER_PICKUP_SHORTFALL"],
    facts: {},
    evidence: {},
    economic_proxy: null,
    source_status: "TRIGGERED",
    ...overrides,
  };
}

describe("buildDecisionCardData", () => {
  it("copies rank and confidence verbatim from the backend's own PrioritySnapshot", () => {
    const item = baseItem({ priority: priority(3, "0.8234") });

    const data = buildDecisionCardData(item);

    expect(data.rank).toBe(3);
    expect(data.confidencePercent).toBe(82);
  });

  it("uses the static Italian title for the decision_type, never the raw code", () => {
    const item = baseItem({});

    expect(buildDecisionCardData(item).title).toBe("Pickup sotto le attese");
    expect(buildDecisionCardData(item).title).not.toContain("REV_PICKUP_LOW");
  });

  it("builds a PICKUP card from the real pickup facts whitelist", () => {
    const item = baseItem({
      target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
      facts: {
        stay_date: "2026-10-01",
        kind: "PICKUP",
        window_days: 7,
        actual_pickup: 3,
        expected_pickup: "7.50",
        delta_rooms: "-4.50",
        missing_rooms: "4.50",
      },
    });

    const data = buildDecisionCardData(item);
    expect(data.card).toEqual({
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 3,
      expectedPickup: "7.50",
      deltaRooms: "-4.50",
      missingRooms: "4.50",
    });
  });

  it("builds an OCCUPANCY card, distinguished from PICKUP by decision_type/target only", () => {
    const item = baseItem({
      decision_type: "REV_OCCUPANCY_RISK",
      target: {
        type: "REV_OCCUPANCY_RISK",
        booking_data_source_id: "src-1",
        stay_date: "2026-10-02",
      },
      facts: {
        kind: "OCCUPANCY",
        forecast_rooms: "40.00",
        expected_final_rooms: "55.00",
        occupancy_gap_pp_exact: "27.27",
        room_shortfall: "15.00",
      },
    });

    const data = buildDecisionCardData(item);
    expect(data.card).toEqual({
      kind: "OCCUPANCY",
      stayDate: "2026-10-02",
      forecastRooms: "40.00",
      expectedFinalRooms: "55.00",
      occupancyGapPp: "27.27",
      roomShortfall: "15.00",
    });
  });

  it("builds an OTA card without accusing a specific OTA and without a recommendation", () => {
    const item = baseItem({
      decision_type: "REV_OTA_DEPENDENCY",
      target: { type: "REV_OTA_DEPENDENCY", booking_data_source_id: "src-1" },
      facts: {
        window_start: "2026-08-01",
        window_end: "2026-09-30",
        ota_share_exact: "62.50",
        expected_ota_share_exact: "45.00",
        structural_condition: true,
        rising_condition: false,
      },
    });

    const data = buildDecisionCardData(item);
    expect(data.card).toEqual({
      kind: "OTA",
      windowStart: "2026-08-01",
      windowEnd: "2026-09-30",
      otaShare: "62.50",
      expectedOtaShare: "45.00",
      structuralCondition: true,
      risingCondition: false,
    });
  });

  it("builds a COST card, carrying the economic proxy separately, never inventing one", () => {
    const item = baseItem({
      decision_type: "COST_CPOR_ANOMALY",
      target: {
        type: "COST_CPOR_ANOMALY",
        booking_data_source_id: "src-1",
        target_period_start: "2026-09-01",
        cost_category: "FOOD_AND_BEVERAGE",
        currency: "EUR",
      },
      facts: {
        actual_cpor_exact: "12.40",
        expected_cpor_exact: "9.00",
        delta_cpor_exact: "3.40",
        delta_percent_exact: "37.78",
      },
      economic_proxy: { label: "cost_gap_proxy", amount: "482.30", currency: "EUR" },
    });

    const data = buildDecisionCardData(item);
    expect(data.card).toEqual({
      kind: "COST",
      costCategory: "FOOD_AND_BEVERAGE",
      periodStart: "2026-09-01",
      currency: "EUR",
      deltaPercent: "37.78",
      actualCpor: "12.40",
      expectedCpor: "9.00",
      deltaCpor: "3.40",
    });
    expect(data.economicProxy).toEqual({ label: "cost_gap_proxy", amount: "482.30", currency: "EUR" });
  });

  it("builds a LABOR card without naming individual employees", () => {
    const item = baseItem({
      decision_type: "LABOR_OVERSTAFFING",
      target: {
        type: "LABOR_OVERSTAFFING",
        booking_data_source_id: "src-1",
        labor_data_source_id: "labor-src-1",
        work_date: "2026-09-25",
        labor_category: "HOUSEKEEPING",
      },
      facts: {
        scheduled_hours_exact: "40.00",
        expected_labor_hours_exact: "28.00",
        excess_hours_exact: "12.00",
      },
    });

    const data = buildDecisionCardData(item);
    expect(data.card).toEqual({
      kind: "LABOR",
      workDate: "2026-09-25",
      laborCategory: "HOUSEKEEPING",
      scheduledHours: "40.00",
      expectedHours: "28.00",
      excessHours: "12.00",
    });
  });

  it("never renders the raw facts object - every field is explicitly named", () => {
    const item = baseItem({
      facts: {
        stay_date: "2026-10-01",
        actual_pickup: 3,
        some_future_field_nobody_mapped_yet: "should not leak",
      },
    });

    const data = buildDecisionCardData(item);
    expect(JSON.stringify(data.card)).not.toContain("should not leak");
  });

  it("degrades gracefully when a numeric fact is absent (e.g. missing_rooms not applicable)", () => {
    const item = baseItem({ facts: { stay_date: "2026-10-01", actual_pickup: 5 } });

    const data = buildDecisionCardData(item);
    expect(data.card).toMatchObject({ missingRooms: null, expectedPickup: null, deltaRooms: null });
  });
});
