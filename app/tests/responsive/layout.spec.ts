/**
 * responsive/layout.spec.ts (Split 08) — fluid re-stacking (UIUX §8).
 *
 * Wide/medium: document + extraction panes side-by-side. Narrow (<900px): the panes STACK with the
 * extraction panel on top (the answer) and the document below (the evidence); hover degrades to
 * tap-to-link (tap a field → scroll to + wash its span). No hard horizontal scrollbar at any width.
 */
import { test, expect } from "@playwright/test";
import { bootExtraction, row } from "../e2e/helpers";

const PANES = "#ce-panes > section";

async function paneBoxes(page: import("@playwright/test").Page) {
  // DOM order under #ce-panes is [document, extraction]; column-reverse flips them visually.
  const doc = await page.locator(PANES).nth(0).boundingBox();
  const extraction = await page.locator(PANES).nth(1).boundingBox();
  return { doc: doc!, extraction: extraction! };
}

async function noHorizontalScroll(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1); // allow sub-pixel rounding
}

test.describe("responsive layout", () => {
  test("wide (1440px) — panes side-by-side, no horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await bootExtraction(page);
    const { doc, extraction } = await paneBoxes(page);
    // Same row (tops roughly aligned) and document is left of extraction.
    expect(Math.abs(doc.y - extraction.y)).toBeLessThan(40);
    expect(doc.x).toBeLessThan(extraction.x);
    await noHorizontalScroll(page);
  });

  test("medium (1024px) — panes still side-by-side", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 820 });
    await bootExtraction(page);
    const { doc, extraction } = await paneBoxes(page);
    expect(Math.abs(doc.y - extraction.y)).toBeLessThan(40);
    expect(doc.x).toBeLessThan(extraction.x);
    await noHorizontalScroll(page);
  });

  test("narrow (560px) — panes STACK with extraction on top", async ({ page }) => {
    await page.setViewportSize({ width: 560, height: 900 });
    await bootExtraction(page);
    const { doc, extraction } = await paneBoxes(page);
    // Stacked: extraction (the answer) sits above the document (the evidence).
    expect(extraction.y + extraction.height).toBeLessThanOrEqual(doc.y + 2);
    await noHorizontalScroll(page);
  });

  test("narrow — tap-to-link: tapping a field scrolls to + washes its span", async ({ page }) => {
    await page.setViewportSize({ width: 560, height: 900 });
    await bootExtraction(page);

    await row(page, "tumor_size_cm").click();
    const mark = page.locator("#ce-mark-active");
    await expect(mark).toBeVisible();
    await expect(mark).toContainText("1.4 cm");
    // Reciprocal row tint confirms the bidirectional link survives the narrow layout.
    await expect(row(page, "tumor_size_cm")).toHaveCSS("background-color", "rgb(244, 246, 249)");
  });
});
