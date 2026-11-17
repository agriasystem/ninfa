// @vitest-environment jsdom
import { render, renderHook } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  PAGE_ROUTES,
  PageContextProvider,
  usePageStateReader,
  usePublishPage,
  type PageState,
} from "./page-context";

function Publisher({ state }: { state: PageState }) {
  usePublishPage(state);
  return null;
}

/** Hands the reader to `onReader` from an effect, so a test can call it at the moment it wants. */
function Reader({ onReader }: { onReader: (read: () => PageState) => void }) {
  const read = usePageStateReader();
  useEffect(() => onReader(read), [onReader, read]);
  return null;
}

/** What the reader returns NOW, from the last one a `Reader` handed over. */
function latestRead(onReader: ReturnType<typeof vi.fn>): PageState {
  const call = onReader.mock.lastCall as [() => PageState] | undefined;
  return call === undefined ? {} : call[0]();
}

function providerWrapper({ children }: { children: ReactNode }) {
  return <PageContextProvider>{children}</PageContextProvider>;
}

describe("the page context", () => {
  it("collects what the screen on display published, as it is when read", () => {
    const onReader = vi.fn();
    render(
      <PageContextProvider>
        <Publisher state={{ route: PAGE_ROUTES.dati, section: "labor", periodDays: 7 }} />
        <Reader onReader={onReader} />
      </PageContextProvider>,
    );

    expect(latestRead(onReader)).toEqual({ route: "/dati", section: "labor", periodDays: 7 });
  });

  it("is empty before anything is published", () => {
    const { result } = renderHook(() => usePageStateReader(), { wrapper: providerWrapper });

    expect(result.current()).toEqual({});
  });

  it("republishes when the state really changes, and the reader sees the new one", () => {
    const onReader = vi.fn();
    const view = (state: PageState) => (
      <PageContextProvider>
        <Publisher state={state} />
        <Reader onReader={onReader} />
      </PageContextProvider>
    );
    const { rerender } = render(view({ route: PAGE_ROUTES.dati, section: "costs" }));
    expect(latestRead(onReader)).toEqual({ route: "/dati", section: "costs" });

    rerender(view({ route: PAGE_ROUTES.dati, section: "labor" }));

    expect(latestRead(onReader)).toEqual({ route: "/dati", section: "labor" });
  });

  it("does not republish when a screen re-renders with an equal state (a new object each time)", () => {
    const onReader = vi.fn();
    const view = () => (
      <PageContextProvider>
        <Publisher state={{ route: PAGE_ROUTES.struttura }} />
        <Reader onReader={onReader} />
      </PageContextProvider>
    );
    const { rerender } = render(view());
    const handedOver = onReader.mock.calls.length;

    rerender(view());
    rerender(view());

    expect(onReader.mock.calls.length).toBe(handedOver); // the reader never changed: nothing re-rendered
    expect(latestRead(onReader)).toEqual({ route: "/struttura" });
  });

  it("withdraws what a screen published when the screen goes away", () => {
    const onReader = vi.fn();
    const { rerender } = render(
      <PageContextProvider>
        <Publisher state={{ route: PAGE_ROUTES.struttura }} />
        <Reader onReader={onReader} />
      </PageContextProvider>,
    );
    expect(latestRead(onReader)).toEqual({ route: "/struttura" });

    rerender(
      <PageContextProvider>
        <Reader onReader={onReader} />
      </PageContextProvider>,
    );

    expect(latestRead(onReader)).toEqual({});
  });

  it("merges several publishers; a later one wins on a key they share, undefined never erases", () => {
    const onReader = vi.fn();
    render(
      <PageContextProvider>
        <Publisher state={{ route: PAGE_ROUTES.dati, section: "overview" }} />
        <Publisher state={{ section: "costs", periodDays: 30, route: undefined }} />
        <Reader onReader={onReader} />
      </PageContextProvider>,
    );

    expect(latestRead(onReader)).toEqual({ route: "/dati", section: "costs", periodDays: 30 });
  });

  it("outside a provider publishing does nothing and the reader gives an empty state", () => {
    expect(() => render(<Publisher state={{ route: PAGE_ROUTES.oggi }} />)).not.toThrow();
    const { result } = renderHook(() => usePageStateReader());

    expect(result.current()).toEqual({});
  });

  it("gives the reader a stable identity between renders", () => {
    const { result, rerender } = renderHook(() => usePageStateReader(), {
      wrapper: providerWrapper,
    });
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });

  it("knows the six canonical route templates of the product registry", () => {
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
  });
});
