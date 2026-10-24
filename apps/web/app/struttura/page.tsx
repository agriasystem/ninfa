"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { StrutturaScreen } from "@/components/struttura-screen";
import { PROPERTY_QUERY_PARAM, strutturaRoute } from "@/lib/routes";

function StrutturaPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);

  function selectProperty(propertyId: string) {
    router.replace(strutturaRoute(propertyId));
  }

  return (
    <StrutturaScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={selectProperty}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function StrutturaPage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <StrutturaPageContent />
    </Suspense>
  );
}
