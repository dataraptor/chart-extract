/**
 * CI-safe e2e launcher (Split 08).
 *
 * The Playwright suite is an OPT-IN extra: it needs a one-time Chromium download
 * (`npx playwright install chromium`). This preflight checks for that browser and, if it's missing,
 * SKIPS the suite cleanly (exit 0) with a hint — so CI and the Python core/api/eval suites stay
 * green on a machine without browsers. When Chromium is present it just delegates to
 * `playwright test`, forwarding any extra args (e.g. `npm run e2e -- money-demo`).
 */
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

let exe = "";
try {
  const { chromium } = await import("@playwright/test");
  exe = chromium.executablePath();
} catch {
  exe = "";
}

if (!exe || !existsSync(exe)) {
  console.log("[e2e] Chromium is not installed — skipping the Playwright suite (CI-safe).");
  console.log("[e2e] Install it once with:  npm run e2e:install   (or  npx playwright install chromium)");
  process.exit(0);
}

const res = spawnSync("npx", ["playwright", "test", ...process.argv.slice(2)], {
  stdio: "inherit",
  shell: true,
});
process.exit(res.status ?? 1);
