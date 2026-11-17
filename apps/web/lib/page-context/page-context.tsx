"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/**
 * What the screen on display SAYS it shows: a small, bounded set of identifiers, collected by the app
 * shell. Each screen publishes its own state (`usePublishPage`); whoever needs to know where the person
 * is - today, Mia - reads it at the moment it matters (`usePageStateReader`).
 *
 * It is deliberately neutral (no assistant, no model, no network in here): the deterministic screens
 * (Dati, Decisioni, Struttura, Importa file) publish through it and still import nothing of Mia. It is
 * only ever identifiers - a route template, a tab id, a period, an id the person selected - never DOM,
 * never HTML, never text typed or shown on the page. How it is turned into what Mia receives, and what
 * is left out on the way, is `lib/mia/ui-context`.
 */

/** The canonical route TEMPLATES (not URLs: a decision detail is one template whatever the id). They
 * are the routes the backend's product knowledge registry knows. */
export const PAGE_ROUTES = {
  oggi: "/oggi",
  decisioni: "/decisioni",
  dati: "/dati",
  importaFile: "/importa-file",
  struttura: "/struttura",
  decisionDetail: "/oggi/decisioni/[decisionId]",
} as const;

export type PageRoute = (typeof PAGE_ROUTES)[keyof typeof PAGE_ROUTES];

export type PageEntityKind = "night" | "data_source" | "cost_category" | "labor_category" | "channel";

/** What a screen may publish. Everything is optional: a screen says only what it really knows. */
export interface PageState {
  route?: PageRoute;
  /** The section inside the page: the Dati tab id on "/dati". */
  section?: string;
  /** 7 or 30 on Dati. */
  periodDays?: number;
  dateFrom?: string;
  dateTo?: string;
  /** The extension point for a selected figure: a metric id of the backend's product registry (for
   * example "metric.occupancy"). No screen publishes one yet - none has a "selected metric" - and no
   * id is ever invented here. */
  metricId?: string;
  decisionId?: string;
  importId?: string;
  entityKind?: PageEntityKind;
  entityId?: string;
}

/** What every screen has published, merged: the one that published later wins on a shared key. */
interface PageStore {
  publish: (publisher: symbol, state: PageState | null) => void;
  read: () => PageState;
}

function createStore(): PageStore {
  const entries = new Map<symbol, PageState>();
  return {
    publish(publisher, state) {
      if (state === null) entries.delete(publisher);
      else entries.set(publisher, state);
    },
    read() {
      const merged: Record<string, unknown> = {};
      for (const state of entries.values()) {
        for (const [key, value] of Object.entries(state)) {
          if (value !== undefined) merged[key] = value;
        }
      }
      return merged as PageState;
    },
  };
}

const PageContext = createContext<PageStore | null>(null);

/** Mounted once, in the app shell: it holds what the screen on display has published. Reading it does
 * not re-render anything - it is read at the moment it is needed. */
export function PageContextProvider({ children }: { children: ReactNode }) {
  const [store] = useState(createStore);
  return <PageContext.Provider value={store}>{children}</PageContext.Provider>;
}

/** Called by a screen to say what it shows. It is withdrawn when the screen goes away, and republished
 * when the state really changes (not on every render). Outside a provider it does nothing. */
export function usePublishPage(state: PageState): void {
  const store = useContext(PageContext);
  const [publisher] = useState(() => Symbol("page"));
  const serialised = JSON.stringify(state);

  useEffect(() => {
    if (store === null) return undefined;
    store.publish(publisher, JSON.parse(serialised) as PageState);
    return () => store.publish(publisher, null);
  }, [store, publisher, serialised]);
}

/** The reader: what the screens have published, as it is at the moment it is called. `{}` outside a
 * provider. Stable between renders. */
export function usePageStateReader(): () => PageState {
  const store = useContext(PageContext);
  return useCallback(() => (store === null ? {} : store.read()), [store]);
}
