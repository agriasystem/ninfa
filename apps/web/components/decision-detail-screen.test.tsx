// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

import { DecisionDetailScreen } from "./decision-detail-screen";

const useSessionMock = vi.fn();
const getDecisionDetailMock = vi.fn();
const getDecisionHistoryMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("@/lib/api/decisions", () => ({
  getDecisionDetail: (...args: unknown[]) => getDecisionDetailMock(...args),
  getDecisionHistory: (...args: unknown[]) => getDecisionHistoryMock(...args),
}));

function property(id: string, name: string): PropertyAccess {
  return { id, name, slug: name.toLowerCase(), timezone: "Europe/Rome" };
}

function session(properties: PropertyAccess[]): SessionContextResponse {
  return {
    user: { id: "u1", email: "a@b.c", display_name: null },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces: [{ id: "ws1", name: "WS", slug: "ws", role: "MEMBER", properties }],
  };
}

beforeEach(() => {
  getDecisionDetailMock.mockReset().mockResolvedValue({
    ok: true,
    data: {
      decision_id: "dec-1",
      decision_type: "REV_PICKUP_LOW",
      status: "OPEN",
      first_seen_local_date: "2026-09-20",
      last_seen_local_date: "2026-09-26",
      last_evaluated_local_date: "2026-09-26",
      resolved_local_date: null,
      episode_count: 1,
      triggered_observation_count: 1,
      target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
      latest_observation: {
        observation_id: "obs-1",
        as_of_local_date: "2026-09-26",
        source_status: "TRIGGERED",
        lifecycle_transition: "OPENED",
        source_evaluation_fingerprint: "fp",
        source_target_key: "key",
        reason_codes: [],
        confidence_score: "0.8",
        priority: null,
        facts: {},
        evidence: {},
        economic_proxy: null,
        memory_version: "v1",
      },
      decision_api_version: "decision-api-v1",
    },
  });
  getDecisionHistoryMock.mockReset().mockResolvedValue({ ok: true, data: { items: [], next_cursor: null } });
});

describe("DecisionDetailScreen - auth", () => {
  it("renders nothing while the session is loading", () => {
    useSessionMock.mockReturnValue({ status: "loading", session: null });

    const { container } = render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="prop-1"
        onNavigateToOggi={vi.fn()}
        onNavigateToLogin={vi.fn()}
      />,
    );

    expect(container.querySelector(".decision-detail__content")).toBeNull();
  });

  it("redirects to login when unauthenticated", async () => {
    useSessionMock.mockReturnValue({ status: "unauthenticated", session: null });
    const onNavigateToLogin = vi.fn();

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="prop-1"
        onNavigateToOggi={vi.fn()}
        onNavigateToLogin={onNavigateToLogin}
      />,
    );

    await waitFor(() => expect(onNavigateToLogin).toHaveBeenCalledOnce());
  });
});

describe("DecisionDetailScreen - property validation", () => {
  it("rejects an unknown/foreign property id client-side and bounces to Oggi for the real one", async () => {
    const properties = [property("prop-1", "Masseria Ninfa")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(properties) });
    const onNavigateToOggi = vi.fn();

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="some-foreign-property"
        onNavigateToOggi={onNavigateToOggi}
        onNavigateToLogin={vi.fn()}
      />,
    );

    await waitFor(() => expect(onNavigateToOggi).toHaveBeenCalledWith("prop-1"));
    expect(getDecisionDetailMock).not.toHaveBeenCalled();
  });

  it("bounces to Oggi (with no property) when the user has zero accessible properties", async () => {
    useSessionMock.mockReturnValue({ status: "authenticated", session: session([]) });
    const onNavigateToOggi = vi.fn();

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="prop-1"
        onNavigateToOggi={onNavigateToOggi}
        onNavigateToLogin={vi.fn()}
      />,
    );

    await waitFor(() => expect(onNavigateToOggi).toHaveBeenCalledWith(null));
    expect(getDecisionDetailMock).not.toHaveBeenCalled();
  });

  it("loads the decision when the URL's property genuinely matches the SessionContext", async () => {
    const properties = [property("prop-1", "Masseria Ninfa")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(properties) });

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="prop-1"
        onNavigateToOggi={vi.fn()}
        onNavigateToLogin={vi.fn()}
      />,
    );

    await waitFor(() => expect(getDecisionDetailMock).toHaveBeenCalledWith("prop-1", "dec-1"));
  });

  it("bounces to Oggi when no property was requested at all (a bare/edited URL)", async () => {
    const properties = [property("prop-1", "Masseria Ninfa")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(properties) });
    const onNavigateToOggi = vi.fn();

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId={null}
        onNavigateToOggi={onNavigateToOggi}
        onNavigateToLogin={vi.fn()}
      />,
    );

    await waitFor(() => expect(onNavigateToOggi).toHaveBeenCalledWith("prop-1"));
    expect(getDecisionDetailMock).not.toHaveBeenCalled();
  });
});

describe("DecisionDetailScreen - switching property from the shell", () => {
  it("navigates to Oggi for the newly selected property, never reusing the current decisionId", async () => {
    const properties = [property("prop-1", "Masseria Ninfa"), property("prop-2", "Villa Astra")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(properties) });
    const onNavigateToOggi = vi.fn();
    const user = userEvent.setup();

    render(
      <DecisionDetailScreen
        decisionId="dec-1"
        requestedPropertyId="prop-1"
        onNavigateToOggi={onNavigateToOggi}
        onNavigateToLogin={vi.fn()}
      />,
    );
    await waitFor(() => expect(getDecisionDetailMock).toHaveBeenCalledWith("prop-1", "dec-1"));

    await user.selectOptions(screen.getByLabelText("Struttura"), "prop-2");

    expect(onNavigateToOggi).toHaveBeenCalledWith("prop-2");
    // Only the original property's decision was ever fetched - never prop-2/dec-1.
    expect(getDecisionDetailMock).toHaveBeenCalledTimes(1);
  });
});
