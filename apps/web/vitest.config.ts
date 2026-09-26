import path from "node:path";

import { defineConfig } from "vitest/config";

// Mirrors tsconfig.json's own "@/*" path mapping (Next.js honours it natively; Vitest does not
// read tsconfig paths on its own). No new dependency: `vitest/config` ships with `vitest` itself.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    setupFiles: ["./test/setup.ts"],
  },
});
