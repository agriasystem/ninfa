// Runs the Next.js CLI with the repository-root `.env` loaded, so that web, api and worker share
// a single environment file. Variables already present in the process environment win over `.env`.
//
//   node scripts/run-next.mjs <dev|build|start> [next args...]
//
// `dev` and `start` also receive --port/--hostname from WEB_PORT/WEB_HOST (port 3000 is left free).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const envFile = path.resolve(appDir, "../../.env");
if (existsSync(envFile)) {
  process.loadEnvFile(envFile);
}

const [command, ...rest] = process.argv.slice(2);
if (!command) {
  console.error("Usage: node scripts/run-next.mjs <dev|build|start> [args...]");
  process.exit(2);
}

const args = [command, ...rest];
if (command === "dev" || command === "start") {
  args.push("--port", process.env.WEB_PORT ?? "3100");
  args.push("--hostname", process.env.WEB_HOST ?? "127.0.0.1");
}

const nextBin = createRequire(import.meta.url).resolve("next/dist/bin/next");
const child = spawn(process.execPath, [nextBin, ...args], { cwd: appDir, stdio: "inherit" });

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code) => process.exit(code ?? 1));
