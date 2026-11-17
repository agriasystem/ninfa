// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import {
  PAGE_ROUTES,
  PageContextProvider,
  usePublishPage,
  type PageState,
} from "@/lib/page-context/page-context";

import { buildMiaUiContext, useMiaUiContextReader } from "./ui-context";

const UUID_A = "6f1c0a52-3b7e-4f1c-9d6a-0b8f5c2e7a11";
const UUID_B = "0a2b3c4d-5e6f-4a1b-8c9d-0e1f2a3b4c5d";

// The only keys the backend's `UiContext` knows. A key outside this list can never leave the browser.
const ALLOWED_KEYS = [
  "route",
  "section",
  "period_days",
  "date_from",
  "date_to",
  "selected_metric",
  "decision_id",
  "import_id",
  "entity_kind",
  "entity_id",
];

describe("buildMiaUiContext", () => {
  it("is empty for a screen that says nothing, and drops every undefined value", () => {
    expect(buildMiaUiContext({})).toEqual({});
    expect(
      buildMiaUiContext({ route: undefined, section: undefined, periodDays: undefined }),
    ).toEqual({});
  });

  it("turns what a screen published into the request's snake_case hint", () => {
    expect(
      buildMiaUiContext({
        route: PAGE_ROUTES.dati,
        section: "costs",
        periodDays: 7,
        dateFrom: "2026-10-01",
        dateTo: "2026-10-07",
        metricId: "metric.occupancy",
        decisionId: UUID_A,
        importId: UUID_B,
        entityKind: "channel",
        entityId: "booking_com",
      }),
    ).toEqual({
      route: "/dati",
      section: "costs",
      period_days: 7,
      date_from: "2026-10-01",
      date_to: "2026-10-07",
      selected_metric: "metric.occupancy",
      decision_id: UUID_A,
      import_id: UUID_B,
      entity_kind: "channel",
      entity_id: "booking_com",
    });
  });

  it("only ever produces keys of the backend's UiContext", () => {
    const everything = buildMiaUiContext({
      route: PAGE_ROUTES.decisionDetail,
      section: "overview",
      periodDays: 30,
      dateFrom: "2026-10-01",
      dateTo: "2026-10-07",
      metricId: "metric.adr",
      decisionId: UUID_A,
      importId: UUID_B,
      entityKind: "night",
      entityId: "2026-10-05",
      // a screen (or a future change) smuggling in text, markup or anything else:
      ...({ html: "<div>x</div>", text: "Il prezzo è 99", dom: "<body/>" } as object),
    } as PageState);

    expect(Object.keys(everything).sort()).toEqual([...ALLOWED_KEYS].sort());
  });

  it("knows the six canonical route templates, and only those", () => {
    expect(Object.values(PAGE_ROUTES).sort()).toEqual(
      [
        "/dati",
        "/decisioni",
        "/importa-file",
        "/oggi",
        "/oggi/decisioni/[decisionId]",
        "/struttura",
      ].sort(),
    );
    expect(buildMiaUiContext({ route: "/oggi/decisioni/abc" as never })).toEqual({});
    expect(buildMiaUiContext({ route: "https://evil.example" as never })).toEqual({});
    expect(buildMiaUiContext({ route: PAGE_ROUTES.decisionDetail }).route).toBe(
      "/oggi/decisioni/[decisionId]",
    );
  });

  it("sends a period only when it is one of the two Dati offers", () => {
    expect(buildMiaUiContext({ periodDays: 7 })).toEqual({ period_days: 7 });
    expect(buildMiaUiContext({ periodDays: 30 })).toEqual({ period_days: 30 });
    expect(buildMiaUiContext({ periodDays: 14 })).toEqual({});
    expect(buildMiaUiContext({ periodDays: 0 })).toEqual({});
  });

  it("leaves out a value the backend would refuse, so a wrong value never breaks a question", () => {
    expect(
      buildMiaUiContext({
        section: "Costs & More",
        metricId: "has space",
        decisionId: "not-a-uuid",
        importId: "123",
        dateFrom: "ieri",
        dateTo: "2026-10-7",
        entityKind: "guest" as never,
        entityId: "x".repeat(65),
      }),
    ).toEqual({});
  });

  it("an entity id travels only with a known entity kind", () => {
    expect(buildMiaUiContext({ entityId: "2026-10-05" })).toEqual({});
    expect(buildMiaUiContext({ entityKind: "night", entityId: "2026-10-05" })).toEqual({
      entity_kind: "night",
      entity_id: "2026-10-05",
    });
    expect(buildMiaUiContext({ entityKind: "night" })).toEqual({ entity_kind: "night" });
  });
});

function Publisher({ state }: { state: PageState }) {
  usePublishPage(state);
  return null;
}

function providerWrapper({ children }: { children: ReactNode }) {
  return <PageContextProvider>{children}</PageContextProvider>;
}

describe("useMiaUiContextReader", () => {
  it("gives the hint of what the screen on display published, read at the moment of use", () => {
    const { result } = renderHook(() => useMiaUiContextReader(), {
      wrapper: ({ children }) => (
        <PageContextProvider>
          <Publisher state={{ route: PAGE_ROUTES.dati, section: "labor", periodDays: 7 }} />
          {children}
        </PageContextProvider>
      ),
    });

    expect(result.current()).toEqual({ route: "/dati", section: "labor", period_days: 7 });
  });

  it("is empty before anything is published, and outside a provider", () => {
    const inside = renderHook(() => useMiaUiContextReader(), { wrapper: providerWrapper });
    const outside = renderHook(() => useMiaUiContextReader());

    expect(inside.result.current()).toEqual({});
    expect(outside.result.current()).toEqual({});
  });

  it("filters what a screen published, exactly like the pure builder", () => {
    const { result } = renderHook(() => useMiaUiContextReader(), {
      wrapper: ({ children }) => (
        <PageContextProvider>
          <Publisher state={{ route: PAGE_ROUTES.dati, section: "Not A Tab", periodDays: 14 }} />
          {children}
        </PageContextProvider>
      ),
    });

    expect(result.current()).toEqual({ route: "/dati" });
  });

  it("is stable between renders (it never re-renders a conversation)", () => {
    const { result, rerender } = renderHook(() => useMiaUiContextReader(), {
      wrapper: providerWrapper,
    });
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });
});
