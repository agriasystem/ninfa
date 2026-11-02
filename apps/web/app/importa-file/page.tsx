"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import type { DataSourceDomain } from "@ninfa/contracts";

import { ImportaFileScreen } from "@/components/importa-file-screen";
import { IMPORTA_FILE_REVIEW_PARAM, importaFileRoute, PROPERTY_QUERY_PARAM } from "@/lib/routes";

/** Only a kind of data NINFA knows is ever passed on from the URL. */
function reviewOf(value: string | null): DataSourceDomain | null {
  return value === "BOOKINGS" || value === "COSTS" || value === "LABOR" ? value : null;
}

function ImportaFilePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);
  const review = reviewOf(searchParams.get(IMPORTA_FILE_REVIEW_PARAM));

  function selectProperty(propertyId: string) {
    router.replace(importaFileRoute(propertyId, review ?? undefined));
  }

  return (
    <ImportaFileScreen
      requestedPropertyId={requestedPropertyId}
      review={review}
      onSelectProperty={selectProperty}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function ImportaFilePage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <ImportaFilePageContent />
    </Suspense>
  );
}
