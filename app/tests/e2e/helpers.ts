/**
 * Shared helpers for the Split 08 Playwright suite.
 *
 * The UI boots in **live** mode against the stub-provider API (the demo's real data path). These
 * helpers wait on *content*, not timers, and assert against the actual stub extraction — never the
 * illustrative spec strings. The expected counts below are the stub's ground truth (confirmed by
 * `POST /api/extract`): pathology grounds all 7 present fields `exact` (→ 0 review) and returns two
 * honest nulls; intake adds a `ListField` and one `needs_review`.
 */
import { Page, expect } from "@playwright/test";

export const PATH_COUNTS = "7 grounded · 2 null (1 not_found · 1 not_assessed)";
export const INTAKE_COUNTS = "8 grounded · 1 null (1 not_found · 0 not_assessed) · 1 review";
export const ROW = '[data-testid="field-row"]';

/** Best-effort: collapse the staged-reveal cadence so tests aren't pacing animations. */
async function fastStream(page: Page): Promise<void> {
  await page
    .evaluate(() => {
      const w = window as any;
      if (w.__dcSetProps && w.__dcRootName) w.__dcSetProps(w.__dcRootName(), { streamMs: 6 });
    })
    .catch(() => {});
}

/**
 * Load the extraction view in live mode and wait until all nine field rows have streamed in.
 * Returns once the demo is in its settled, fully-populated state.
 */
export async function bootExtraction(page: Page): Promise<void> {
  await page.goto("/");
  // The DC runtime fetches React/Babel from unpkg, then mounts; wait for the shell.
  await expect(page.getByText("ChartExtract").first()).toBeVisible({ timeout: 30_000 });
  await fastStream(page);
  await expect(page.locator(ROW)).toHaveCount(9, { timeout: 30_000 });
}

/** Switch the active sample (pathology ⇄ intake) and wait for the re-extraction to settle. */
export async function switchSample(page: Page, label: "Pathology" | "Intake"): Promise<void> {
  await page.getByRole("button", { name: label, exact: true }).click();
  await fastStream(page);
  await expect(page.locator(ROW)).toHaveCount(9, { timeout: 30_000 });
}

/** The row element for a field by its engine name (e.g. `tumor_size_cm`, `medications[0]`). */
export function row(page: Page, field: string) {
  return page.locator(`${ROW}[data-field="${field}"]`);
}

/** Fetch the raw stub ExtractionResult so tests can cross-check rendered offsets against the API. */
export async function fetchExtract(
  page: Page,
  sampleId: string,
  schema: string,
): Promise<any> {
  const res = await page.request.post("/api/extract", {
    data: { sample_id: sampleId, schema },
  });
  expect(res.ok()).toBeTruthy();
  return res.json();
}
