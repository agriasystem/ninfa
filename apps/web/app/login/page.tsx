"use client";

import { useRouter } from "next/navigation";

import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  const router = useRouter();

  return (
    <main className="login-page">
      <LoginForm onSuccess={() => router.replace("/oggi")} />
    </main>
  );
}
