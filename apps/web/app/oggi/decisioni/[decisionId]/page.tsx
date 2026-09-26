"use client";

import { Suspense } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { DecisionDetailScreen } from "@/components/decision-detail-screen";
import { oggiRoute, PROPERTY_QUERY_PARAM } from "@/lib/routes";

function DecisionDetailPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ decisionId: string }>();
  const requestedPropertyId = searchParams.get(PROPERTY_QUERY_PARAM);

  return (
    <DecisionDetailScreen
      decisionId={params.decisionId}
      requestedPropertyId={requestedPropertyId}
      onNavigateToOggi={(propertyId) => router.replace(oggiRoute(propertyId ?? undefined))}
      onNavigateToLogin={() => router.replace("/login")}
    />
  );
}

// `useSearchParams()` requires a Suspense boundary so Next.js can still prerender the page shell.
export default function DecisionDetailPage() {
  return (
    <Suspense fallback={<div className="root-page__loading" aria-live="polite" aria-busy="true" />}>
      <DecisionDetailPageContent />
    </Suspense>
  );
}
