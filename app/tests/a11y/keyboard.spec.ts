/**
 * a11y/keyboard.spec.ts (Split 08) — keyboard parity (UIUX §9).
 *
 * Focusing a field row must drive the SAME wash + doc glide as hover; arrow keys move between rows;
 * Enter pins; Esc clears pins; nothing traps. A visible 2px focus ring is asserted.
 */
import { test, expect } from "@playwright/test";
import { bootExtraction, row, ROW } from "../e2e/helpers";

test.describe("keyboard parity", () => {
  test("focusing a row washes its span (same as hover) and shows a focus ring", async ({ page }) => {
    await bootExtraction(page);

    const tumor = row(page, "tumor_size_cm");
    await tumor.focus();
    // Focus drives the wash: the active mark appears at the field's span.
    await expect(page.locator("#ce-mark-active")).toBeVisible();
    await expect(page.locator("#ce-mark-active")).toContainText("1.4 cm");

    // Visible 2px focus ring (outline) on the focused row.
    const outline = await tumor.evaluate((el) => getComputedStyle(el).outlineWidth);
    expect(outline).toBe("2px");
  });

  test("arrow keys move focus between rows", async ({ page }) => {
    await bootExtraction(page);
    await row(page, "specimen").focus();
    await expect(row(page, "specimen")).toBeFocused();

    await page.keyboard.press("ArrowDown");
    await expect(row(page, "diagnosis")).toBeFocused();

    await page.keyboard.press("ArrowUp");
    await expect(row(page, "specimen")).toBeFocused();
  });

  test("Enter pins a span; Esc clears all pins; no keyboard trap", async ({ page }) => {
    await bootExtraction(page);

    await row(page, "tumor_size_cm").focus();
    await page.keyboard.press("Enter");
    // Pinned: blur the row (move focus) and the span stays lit.
    await row(page, "er_status").focus();
    await page.keyboard.press("Enter");
    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await expect(page.locator("#ce-doc mark")).toHaveCount(2);

    // Esc from a row clears every pin (focus still washes the focused row, so blur to confirm
    // the pins themselves are gone).
    await row(page, "er_status").focus();
    await page.keyboard.press("Escape");
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
    await expect(page.locator("#ce-doc mark")).toHaveCount(0);

    // No trap: Tab from a focused row always moves focus to a different element.
    await row(page, "her2_status").focus();
    await page.keyboard.press("Tab");
    const movedAway = await page.evaluate(
      () => document.activeElement?.getAttribute("data-field") !== "her2_status",
    );
    expect(movedAway).toBeTruthy();
  });
});
