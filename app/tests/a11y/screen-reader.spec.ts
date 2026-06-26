/**
 * a11y/screen-reader.spec.ts (Split 08) — accessible names + live region + non-color signals (§9).
 *
 * Each field row exposes an accessible name conveying name / value-or-null / flag meaning /
 * confidence / match-quality; nulls announce the *reason*; the stream region is `aria-live=polite`;
 * every flag pairs its color with an icon + text label (color is never the only signal).
 */
import { test, expect } from "@playwright/test";
import { bootExtraction, switchSample, row } from "../e2e/helpers";

test.describe("screen-reader semantics", () => {
  test("a present field announces value, flag, confidence and match quality", async ({ page }) => {
    await bootExtraction(page);
    const aria = await row(page, "tumor_size_cm").getAttribute("aria-label");
    expect(aria).toContain("tumor_size_cm");
    expect(aria).toContain("1.4");
    expect(aria).toContain("accepted");
    expect(aria).toContain("confidence");
    expect(aria).toContain("exact match");
  });

  test("nulls announce the REASON, not just 'null'", async ({ page }) => {
    await bootExtraction(page);
    const assessed = await row(page, "margin_status").getAttribute("aria-label");
    expect(assessed).toContain("null");
    expect(assessed).toContain("not assessed");
    expect(assessed).toContain("document states it was not determined");

    const found = await row(page, "lymph_nodes_positive").getAttribute("aria-label");
    expect(found).toContain("null");
    expect(found).toContain("not found");
    expect(found).toContain("no mention in the document");
  });

  test("the streaming field list is an aria-live polite region", async ({ page }) => {
    await bootExtraction(page);
    const region = page.getByTestId("fields");
    await expect(region).toHaveAttribute("aria-live", "polite");
  });

  test("color is never the only signal — every flag carries an icon + text label", async ({
    page,
  }) => {
    await bootExtraction(page);
    // accepted shows the ✓ + 'accepted' text (not just the green bar).
    await expect(row(page, "specimen")).toContainText("✓ accepted");
    await expect(row(page, "margin_status")).toContainText("⊘ not assessed");
    await expect(row(page, "lymph_nodes_positive")).toContainText("∅ not found");

    // needs_review surfaces in the intake sample (chief_complaint, mc 0.55 < τ).
    await switchSample(page, "Intake");
    await expect(row(page, "chief_complaint")).toContainText("⚠ needs review");
  });
});
