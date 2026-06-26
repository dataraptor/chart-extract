/**
 * a11y/axe.spec.ts (Split 08) — automated WCAG scan (axe-core) on the two primary views.
 *
 * Gate: **0 serious or critical** violations on the extraction view and the eval leaderboard. The
 * suite runs on the stub stack so the DOM is deterministic. Any violation here is a real a11y bug to
 * fix in the UI (e.g. contrast, missing names) — never suppressed.
 */
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { bootExtraction } from "../e2e/helpers";

const SEVERE = ["serious", "critical"];

function severe(violations: any[]) {
  return violations
    .filter((v) => SEVERE.includes(v.impact))
    .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n: any) => n.target) }));
}

test.describe("axe — WCAG AA", () => {
  test("extraction view has no serious/critical violations", async ({ page }) => {
    await bootExtraction(page);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(severe(results.violations)).toEqual([]);
  });

  test("eval leaderboard has no serious/critical violations", async ({ page }) => {
    await bootExtraction(page);
    await page.getByRole("button", { name: "Eval", exact: true }).click();
    await expect(page.getByTestId("eval-halluc")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(severe(results.violations)).toEqual([]);
  });
});
