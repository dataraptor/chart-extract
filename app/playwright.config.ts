/**
 * Playwright config (Split 08) — cross-stack e2e / a11y / responsive suite for the ChartExtract UI.
 *
 * The suite drives the *already-wired* `app/` DC UI against a real `chartextract-api` running on the
 * **stub provider** (keyless → deterministic, no live model call, CI-safe). A `webServer` block boots
 * that API on a fixed port before the tests and serves the UI same-origin at `/`, so the whole money
 * demo is exercised exactly as a buyer would hit it.
 *
 * Determinism: the stub provider returns fixed extractions; tests assert against the *actual* stub
 * counts (path = 7 grounded · 2 null · 0 review; intake = 8 · 1 · 1), never the illustrative spec
 * strings. Animations are made instant per-test (low `streamMs` via the DC props bridge + waiting on
 * content, not timers).
 *
 * CI-safe skip: if the Chromium browser isn't installed, Playwright fails fast with a clear message;
 * the `make e2e` / npm script documents the one-time `npx playwright install chromium`. The Python
 * core/api/eval suites never import this — it is a separate, opt-in JS test stack.
 */
import { defineConfig, devices } from "@playwright/test";
import * as path from "path";

const PORT = Number(process.env.CE_E2E_PORT || 8788);
const HOST = "127.0.0.1";
const BASE_URL = `http://${HOST}:${PORT}`;
const REPO_ROOT = path.resolve(__dirname, "..");

// The Python interpreter that has `chartextract` + `chartextract_api` installed (this box has no
// `python` on PATH — see 00-PROGRESS Split 01 note). Overridable for other environments.
const PYTHON = process.env.CE_PYTHON || "C:/ProgramData/miniconda3/python.exe";

export default defineConfig({
  testDir: "./tests",
  // Only the Playwright specs — NOT the node:test files (`*.test.js` for map.js/api.js).
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    trace: "off",
    video: "off",
    screenshot: "off",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  // Boot the stub-provider API (keyless env → stub) from the repo root before the suite.
  webServer: {
    command: `"${PYTHON}" -m uvicorn chartextract_api.app:app --host ${HOST} --port ${PORT}`,
    cwd: REPO_ROOT,
    url: `${BASE_URL}/health`,
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
    env: {
      // Force the stub provider: no live credentials in the server's environment.
      OPENAI_API_KEY: "",
      AZURE_OPENAI_API_KEY: "",
      ANTHROPIC_API_KEY: "",
      // Split 09: enable the dev-only ?simulate=<type> edge-state hook so the edge specs can drive
      // each designed failure/unusual-input state deterministically (disabled in prod).
      CHARTEXTRACT_DEV: "1",
    },
  },
});
