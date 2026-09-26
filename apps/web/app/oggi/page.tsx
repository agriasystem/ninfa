"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { OggiScreen } from "@/components/oggi-screen";

const PROPERTY_QUERY_PARAM = "property";

function OggiPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);

  function selectProperty(propertyId: string) {
    const params = new URLSearchParams(searchParams);
    params.set(PROPERTY_QUERY_PARAM, propertyId);
    router.replace(`/oggi?${params.toString()}`);
  }

  return (
    <OggiScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={selectProperty}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function OggiPage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <OggiPageContent />
    </Suspense>
  );
}
