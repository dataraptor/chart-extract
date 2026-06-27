/**
 * screenshots/shots.spec.ts (Split 08) — the §10 shot list, generated deterministically.
 *
 * Eight portfolio frames written to `docs/screenshots/` (Split 10's README embeds them). These are
 * ARTIFACTS, not assertions — but each capture step must run green. Frames are stabilised with
 * reduced-motion (so washes/glows are at their settled end-state) on the deterministic stub stack.
 *
 * `07-no-text-layer-banner` is owned by Split 09 (the no-text-layer edge state isn't built yet) and
 * is skipped here with a note — regenerate once Split 09 lands.
 */
import { test, expect } from "@playwright/test";
import * as path from "path";
import { bootExtraction, switchSample, row } from "../e2e/helpers";

const OUT = path.resolve(__dirname, "../../..", "docs", "screenshots");
const WIDE = { width: 1440, height: 900 };

test.describe("§10 shot list", () => {
  test.beforeEach(async ({ page }) => {
    // Settle washes/glows to their end-state so frames are pixel-stable.
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("01-extraction-hero-hover", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    await row(page, "tumor_size_cm").hover();
    await expect(page.locator("#ce-mark-active")).toBeVisible();
    await page.screenshot({ path: path.join(OUT, "01-extraction-hero-hover.png") });
  });

  test("02-two-honest-nulls", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    await row(page, "margin_status").click(); // pin the cited not_assessed (cyan wash)
    await row(page, "lymph_nodes_positive").hover(); // grey not_found (nothing washes)
    await expect(page.locator("#ce-doc mark")).toHaveCount(1);
    await page.screenshot({ path: path.join(OUT, "02-two-honest-nulls.png") });
  });

  test("03-not-grounded-caught", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    // The path-only "show caught hallucination" toggle swaps in the not_grounded variant.
    await page.getByRole("button", { name: "Show caught hallucination" }).click();
    await expect(row(page, "lymph_nodes_positive")).toContainText("not grounded");
    await row(page, "lymph_nodes_positive").hover();
    await page.screenshot({ path: path.join(OUT, "03-not-grounded-caught.png") });
  });

  test("04-eval-leaderboard", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    await page.getByRole("button", { name: "Eval", exact: true }).click();
    await expect(page.getByTestId("eval-halluc")).toBeVisible();
    await page.screenshot({ path: path.join(OUT, "04-eval-leaderboard.png") });
  });

  test("05-streaming-state", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    // This frame NEEDS motion (the staged reveal) — undo the reduced-motion default for it.
    await page.emulateMedia({ reducedMotion: "no-preference" });
    // Re-stream slowly and freeze mid-reveal (some rows landed, the rest still ghost skeletons).
    await page.evaluate(() => {
      const w = window as any;
      if (w.__dcSetProps && w.__dcRootName) w.__dcSetProps(w.__dcRootName(), { streamMs: 600 });
    });
    await page.locator('button[title="Re-run extraction"]').click();
    await page.waitForFunction(() => {
      const n = document.querySelectorAll('[data-testid="field-row"]').length;
      return n >= 3 && n < 9;
    });
    await page.screenshot({ path: path.join(OUT, "05-streaming-state.png") });
  });

  test("06-listfield-intake", async ({ page }) => {
    await page.setViewportSize(WIDE);
    await bootExtraction(page);
    await switchSample(page, "Intake");
    await row(page, "medications[0]").hover();
    await page.screenshot({ path: path.join(OUT, "06-listfield-intake.png") });
  });

  test("07-no-text-layer-banner", async ({ page }) => {
    await page.setViewportSize(WIDE);
    // Split 09: the dev simulate hook returns a vision-fallback record (highlight_available:false).
    await page.goto("/?simulate=no_text_layer");
    await expect(page.getByText("ChartExtract").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-notice-type="no_text_layer"]')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-testid="highlight-na"]').first()).toBeVisible();
    await page.screenshot({ path: path.join(OUT, "07-no-text-layer-banner.png") });
  });

  test("08-narrow-stacked", async ({ page }) => {
    await page.setViewportSize({ width: 560, height: 900 });
    await bootExtraction(page);
    await row(page, "tumor_size_cm").click(); // tap-to-link: scroll to + wash the span
    await expect(page.locator("#ce-mark-active")).toBeVisible();
    await page.screenshot({ path: path.join(OUT, "08-narrow-stacked.png") });
  });
});
