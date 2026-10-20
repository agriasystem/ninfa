"use client";

import type { DataOverviewResponse, DataPeriod } from "@ninfa/contracts";

import { datiCopy } from "@/lib/data/copy";
import type { DatiTab } from "@/lib/data/tabs";
import { useDataOverview } from "@/lib/data/use-data-overview";

import { DatiSkeleton } from "./dati-skeleton";
import { DatiOverviewPanel } from "./dati-overview-panel";
import {
  DatiBookingsPanel,
  DatiCostsPanel,
  DatiDistributionPanel,
  DatiLaborPanel,
} from "./dati-secondary-panels";
import { datiPanelId, datiTabId, DatiTabs } from "./dati-tabs";
import { PropertyScreen } from "./property-screen";
import { RefreshButton } from "./refresh-button";

interface DatiContentProps {
  propertyId: string;
  timeZone: string;
  tab: DatiTab;
  period: DataPeriod;
  onSelectTab: (tab: DatiTab) => void;
  onSelectPeriod: (period: DataPeriod) => void;
  onPropertyInvalid: () => void;
}

function Panel({
  tab,
  overview,
  propertyId,
  timeZone,
  period,
  busy,
  onSelectPeriod,
}: {
  tab: DatiTab;
  overview: DataOverviewResponse;
  propertyId: string;
  timeZone: string;
  period: DataPeriod;
  busy: boolean;
  onSelectPeriod: (period: DataPeriod) => void;
}) {
  const shared = { overview, propertyId, timeZone };
  switch (tab) {
    case "overview":
      return <DatiOverviewPanel {...shared} period={period} busy={busy} onSelectPeriod={onSelectPeriod} />;
    case "bookings":
      return <DatiBookingsPanel {...shared} period={period} busy={busy} onSelectPeriod={onSelectPeriod} />;
    case "distribution":
      return <DatiDistributionPanel {...shared} />;
    case "costs":
      return <DatiCostsPanel {...shared} />;
    case "labor":
      return <DatiLaborPanel {...shared} />;
  }
}

/**
 * The Dati workspace of ONE property: its own title, the five internal tabs, and the selected view of
 * a single deterministic overview. The header and the tabs are always on screen - while the data
 * loads they sit above card-shaped skeletons, and an error stays inside the page (shell and tabs
 * preserved) with a "Riprova". No part of this screen calls Mia or any model.
 */
function DatiContent({
  propertyId,
  timeZone,
  tab,
  period,
  onSelectTab,
  onSelectPeriod,
  onPropertyInvalid,
}: DatiContentProps) {
  const { busy, data, failed, refresh } = useDataOverview({
    propertyId,
    timeZone,
    period,
    onPropertyInvalid,
  });

  return (
    <div className="dati-screen">
      <header className="dati-screen__header">
        <div className="dati-screen__title-row">
          <h1>{datiCopy.heading}</h1>
          <RefreshButton busy={busy} onRefresh={() => void refresh()} label={datiCopy.refresh} />
        </div>
        <p className="dati-screen__subtitle">{datiCopy.subtitle}</p>
      </header>

      <DatiTabs active={tab} onSelect={onSelectTab} />

      <div
        role="tabpanel"
        id={datiPanelId(tab)}
        aria-labelledby={datiTabId(tab)}
        tabIndex={-1}
        className="dati-screen__panel"
        data-period-busy={data !== null && busy ? "true" : "false"}
      >
        {data !== null ? (
          <Panel
            tab={tab}
            overview={data}
            propertyId={propertyId}
            timeZone={timeZone}
            period={period}
            busy={busy}
            onSelectPeriod={onSelectPeriod}
          />
        ) : failed ? (
          <div className="dati-error" role="alert">
            <p>{datiCopy.loadError}</p>
            <button type="button" onClick={() => void refresh()}>
              {datiCopy.retry}
            </button>
          </div>
        ) : (
          <DatiSkeleton />
        )}
      </div>
    </div>
  );
}

export interface DatiScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  tab: DatiTab;
  period: DataPeriod;
  onSelectProperty: (propertyId: string) => void;
  onSelectTab: (tab: DatiTab) => void;
  onSelectPeriod: (period: DataPeriod) => void;
  onNavigateToLogin: () => void;
}

/** The full "/dati" screen: auth bootstrap gate, property resolution (0 / 1 / N properties), the
 * sidebar shell with "Dati" active, and the workspace. Framework-free - `app/dati/page.tsx` wires it
 * to the real router; this is what gets tested. */
export function DatiScreen({
  requestedPropertyId,
  tab,
  period,
  onSelectProperty,
  onSelectTab,
  onSelectPeriod,
  onNavigateToLogin,
}: DatiScreenProps) {
  return (
    <PropertyScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={onSelectProperty}
      onNavigateToLogin={onNavigateToLogin}
      activeSection="dati"
      variant="wide"
    >
      {(selected, onPropertyInvalid) => (
        <DatiContent
          propertyId={selected.id}
          timeZone={selected.timezone}
          tab={tab}
          period={period}
          onSelectTab={onSelectTab}
          onSelectPeriod={onSelectPeriod}
          onPropertyInvalid={onPropertyInvalid}
        />
      )}
    </PropertyScreen>
  );
}
