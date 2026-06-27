/**
 * edge-states.spec.ts (Split 09) — every designed failure / unusual-input state, driven by a REAL
 * backend signal against the `api(stub)+app` stack.
 *
 * The error / degraded states use the dev-only `?simulate=<type>` hook (enabled in the Playwright
 * webServer via `CHARTEXTRACT_DEV=1`); the upload state drives a genuine multipart request. Each
 * test asserts the state renders per the UIUX spec — banner copy, amber blocking dropdown, dotted
 * ambiguous mark, upload error, ListField collapse — and that nothing crashes or blanks (§9).
 */
import { test, expect, Page } from "@playwright/test";
import { bootExtraction, switchSample, row } from "../e2e/helpers";

const ROW = '[data-testid="field-row"]';
const NOTICE = '[data-testid="notice"]';

/** Navigate (optionally with a ?simulate= type) and wait for the DC shell to mount. */
async function boot(page: Page, query = ""): Promise<void> {
  await page.goto("/" + query);
  await expect(page.getByText("ChartExtract").first()).toBeVisible({ timeout: 30_000 });
}

async function fastStream(page: Page): Promise<void> {
  await page
    .evaluate(() => {
      const w = window as any;
      if (w.__dcSetProps && w.__dcRootName) w.__dcSetProps(w.__dcRootName(), { streamMs: 6 });
    })
    .catch(() => {});
}

test.describe("Split 09 — edge states", () => {
  test("no-text-layer → highlight-disabled banner, values still render, no doc marks", async ({
    page,
  }) => {
    await boot(page, "?simulate=no_text_layer");
    await fastStream(page);
    // the warning banner with the spec copy
    const banner = page.locator('[data-notice-type="no_text_layer"]');
    await expect(banner).toBeVisible({ timeout: 30_000 });
    await expect(banner).toContainText(/highlighting disabled/i);
    // the doc header flips honestly + rows show the "highlight n/a" affordance, values still present
    await expect(page.getByTestId("doc-layer-status")).toContainText(/no text layer/i);
    await expect(page.locator('[data-testid="highlight-na"]').first()).toBeVisible();
    await expect(row(page, "specimen")).toContainText("Left breast core biopsy");
    // highlighting is honestly disabled — hovering a row washes nothing in the document.
    await row(page, "tumor_size_cm").hover();
    await expect(page.locator("#ce-doc mark")).toHaveCount(0);
  });

  test("refusal → calm skip notice, UI stays usable, no crash", async ({ page }) => {
    await boot(page, "?simulate=refusal");
    const notice = page.locator(`[data-notice-type="refusal"]`);
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await expect(notice).toContainText(/safety classifier/i);
    // no field rows for a skipped doc, but the command bar stays usable (schema toggle present).
    await expect(page.locator(ROW)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Pathology", exact: true })).toBeVisible();
  });

  test("truncation → auto-retry, then a fresh full record streams (never a partial)", async ({
    page,
  }) => {
    await boot(page, "?simulate=truncated");
    await fastStream(page);
    // the retry drops the simulate hook (mirrors the provider's bounded headroom retry) and the
    // fresh, complete stub record streams in — all nine rows, never a partial.
    await expect(page.locator(ROW)).toHaveCount(9, { timeout: 30_000 });
    await expect(page.getByTestId("footer-counts")).toContainText("7 grounded");
  });

  test("unknown routing → amber 'choose a schema' blocks until the human picks", async ({
    page,
  }) => {
    await boot(page, "?simulate=unknown_doc_type");
    await expect(page.getByTestId("route-block-chip")).toContainText(/choose a schema/i);
    // extraction is blocked: no rows until a schema is chosen (never silently defaults).
    await expect(page.locator(ROW)).toHaveCount(0);
    await expect(page.locator(`[data-notice-type="unknown_doc_type"]`)).toBeVisible();
    // picking a schema clears the block and re-extracts for real.
    await page.getByRole("button", { name: "Pathology", exact: true }).click();
    await fastStream(page);
    await expect(page.locator(ROW)).toHaveCount(9, { timeout: 30_000 });
    await expect(page.getByTestId("route-block-chip")).toHaveCount(0);
  });

  test("misroute → non-blocking 'looks misrouted — change schema?' hint", async ({ page }) => {
    await boot(page, "?simulate=misroute");
    await fastStream(page);
    await expect(page.getByTestId("misroute-hint")).toContainText(/looks misrouted/i);
    // it is a hint, not a block — rows still render (mostly not_found).
    await expect(page.locator(ROW).first()).toBeVisible({ timeout: 30_000 });
  });

  test("unsupported upload → inline 'text-layer PDF or .txt only'", async ({ page }) => {
    await boot(page);
    await page.locator('[data-testid="upload-input"]').setInputFiles({
      name: "scan.png",
      mimeType: "image/png",
      buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
    });
    const notice = page.locator(`[data-notice-type="unsupported_file"]`);
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await expect(notice).toContainText(/\.txt only/i);
  });

  test("supported upload (.txt) flows through the normal extract path", async ({ page }) => {
    await boot(page);
    await fastStream(page);
    await page.locator('[data-testid="upload-input"]').setInputFiles({
      name: "note.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "SURGICAL PATHOLOGY REPORT\nSPECIMEN: Left breast core biopsy.\nTumor size 1.4 cm.\n"
      ),
    });
    // a valid text-layer upload runs the engine and renders rows (no error notice).
    await expect(page.locator(ROW).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(NOTICE)).toHaveCount(0);
  });

  test("ListField group → collapsible 'medications · k of n grounded' over the per-item rows", async ({
    page,
  }) => {
    await bootExtraction(page);
    await switchSample(page, "Intake");
    const group = page.locator('[data-testid="listfield-group"][data-group="medications"]');
    await expect(group).toContainText(/medications · 3 of 3 grounded/);
    // items are present, then collapse hides them (per-item grounding is preserved, not flattened).
    await expect(row(page, "medications[0]")).toBeVisible();
    await group.getByRole("button").click();
    await expect(row(page, "medications[0]")).toHaveCount(0);
    // re-expand restores them.
    await group.getByRole("button").click();
    await expect(row(page, "medications[0]")).toBeVisible();
  });

  test("offline honesty → 'canned data' chip shown when the backend runs the stub", async ({
    page,
  }) => {
    await boot(page);
    // the e2e backend is keyless → stub provider; the standing offline chip makes that honest.
    await expect(page.getByTestId("offline-chip")).toBeVisible({ timeout: 30_000 });
  });

  test("ambiguous → dotted-underline mark + 'matched N · 1 of N' tag (no silent first-match)", async ({
    page,
  }) => {
    await boot(page, "?simulate=ambiguous");
    await fastStream(page);
    await expect(page.locator(ROW).first()).toBeVisible({ timeout: 30_000 });
    const er = row(page, "er_status");
    await expect(er).toContainText(/1 of \d/);
    await expect(er).toContainText(/ambiguous/i);
    // the first match washes amber with a dotted underline (the anti-silent-wrong-highlight state).
    await er.hover();
    const mark = page.locator("#ce-doc mark").first();
    await expect(mark).toBeVisible();
    await expect(mark).toHaveCSS("text-decoration-style", "dotted");
  });
});
