/**
 * a11y/reduced-motion.spec.ts (Split 08) — `prefers-reduced-motion: reduce` (§9).
 *
 * Under reduced motion the staged reveal and CSS glides/glows/count-ups become instant; the washes
 * and final numbers still appear. Nothing essential is gated behind animation.
 */
import { test, expect } from "@playwright/test";
import { row } from "../e2e/helpers";

test.describe("reduced motion", () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("all rows + final counts appear instantly; transitions are disabled", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("ChartExtract").first()).toBeVisible({ timeout: 30_000 });

    // Reveal is instant — all nine rows are present without waiting out the stagger.
    await expect(page.locator('[data-testid="field-row"]')).toHaveCount(9, { timeout: 30_000 });
    // Final counts still render.
    await expect(page.getByTestId("footer-counts")).toContainText("7 grounded");

    // Row background transition is collapsed to ~instant by the reduced-motion stylesheet rule.
    const dur = await row(page, "specimen").evaluate((el) =>
      parseFloat(getComputedStyle(el).transitionDuration),
    );
    expect(dur).toBeLessThan(0.01);
  });

  test("the hover wash still works under reduced motion", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="field-row"]')).toHaveCount(9, { timeout: 30_000 });
    await row(page, "tumor_size_cm").hover();
    await expect(page.locator("#ce-mark-active")).toBeVisible();
    await expect(page.locator("#ce-mark-active")).toContainText("1.4 cm");
  });
});
