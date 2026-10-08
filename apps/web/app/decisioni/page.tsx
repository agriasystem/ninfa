"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { DecisioniScreen } from "@/components/decisioni-screen";
import { decisioniRoute, PROPERTY_QUERY_PARAM } from "@/lib/routes";

function DecisioniPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);

  function selectProperty(propertyId: string) {
    router.replace(decisioniRoute(propertyId));
  }

  return (
    <DecisioniScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={selectProperty}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function DecisioniPage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <DecisioniPageContent />
    </Suspense>
  );
}
