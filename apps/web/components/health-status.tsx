"use client";

import { useEffect, useState } from "react";

import { fetchHealth, type HealthResult } from "@/lib/health";

function describe(result: HealthResult | null): { message: string; detail?: string } {
  if (result === null) return { message: "Checking system…" };
  switch (result.state) {
    case "ok":
      return {
        message: "System operational",
        detail: `${result.health.service} v${result.health.version}`,
      };
    case "unreachable":
      return { message: "System unreachable", detail: result.reason };
    case "misconfigured":
      return { message: "Frontend misconfigured", detail: result.reason };
  }
}

export function HealthStatus() {
  const [result, setResult] = useState<HealthResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(process.env.NEXT_PUBLIC_API_BASE_URL, fetch, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResult(value);
    });
    return () => controller.abort();
  }, []);

  const { message, detail } = describe(result);
  return (
    <div role="status">
      <p>{message}</p>
      {detail ? <p className="detail">{detail}</p> : null}
    </div>
  );
}
