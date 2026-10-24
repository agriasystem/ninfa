"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import type { DataPeriod } from "@ninfa/contracts";

import { DatiScreen } from "@/components/dati-screen";
import { parseDataPeriod, parseDatiTab, type DatiTab } from "@/lib/data/tabs";
import { DATI_PERIOD_PARAM, DATI_TAB_PARAM, datiRoute, PROPERTY_QUERY_PARAM } from "@/lib/routes";

function DatiPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);
  const tab = parseDatiTab(searchParams.get(DATI_TAB_PARAM));
  const period = parseDataPeriod(searchParams.get(DATI_PERIOD_PARAM));

  // Resolving the property (a first visit, a foreign id corrected to a real one) REPLACES the entry:
  // it is not a step the user took, so back must not return to the unresolved URL.
  function selectProperty(propertyId: string) {
    router.replace(datiRoute(propertyId, { tab, period }));
  }

  // A tab or a period the user chooses IS a step: back / forward walk through them.
  function selectTab(next: DatiTab) {
    if (requestedPropertyId === null) return;
    router.push(datiRoute(requestedPropertyId, { tab: next, period }));
  }

  function selectPeriod(next: DataPeriod) {
    if (requestedPropertyId === null) return;
    router.push(datiRoute(requestedPropertyId, { tab, period: next }));
  }

  return (
    <DatiScreen
      requestedPropertyId={requestedPropertyId}
      tab={tab}
      period={period}
      onSelectProperty={selectProperty}
      onSelectTab={selectTab}
      onSelectPeriod={selectPeriod}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function DatiPage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <DatiPageContent />
    </Suspense>
  );
}
