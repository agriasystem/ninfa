import { HealthStatus } from "@/components/health-status";

// Gate 0 technical shell: proves that the frontend runs and can reach the API. Not product UI.
export default function Home() {
  return (
    <main>
      <h1>NINFA</h1>
      <HealthStatus />
    </main>
  );
}
