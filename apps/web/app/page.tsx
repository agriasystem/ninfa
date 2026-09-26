"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/session/session-context";

/** Root "/": never a page of its own content - it only ever decides, once the auth bootstrap
 * call has answered, whether to send the browser to /oggi or /login. Never shows anything that
 * looks like authenticated content while that answer is still unknown. */
export default function RootPage() {
  const router = useRouter();
  const { status } = useSession();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/oggi");
    } else if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  return <div className="root-page__loading" aria-live="polite" aria-busy="true" />;
}
