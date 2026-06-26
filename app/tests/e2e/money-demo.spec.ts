/**
 * money-demo.spec.ts (Split 08) — the §6 money-demo choreography, beat by beat, against the live
 * `api(stub) + app` stack served same-origin.
 *
 * Determinism: every assertion is derived from the *actual* stub extraction (counts, offsets,
 * flags), never the illustrative spec strings. The stub grounds all seven present pathology fields
 * `exact` (→ 0 review) and returns the two honest nulls — `margin_status` (`not_assessed`, cited)
 * and `lymph_nodes_positive` (`not_found`, silent).
 */
import { test, expect } from "@playwright/test";
import { bootExtraction, row, fetchExtract, PATH_COUNTS } from "./helpers";

test.describe("money demo — §6 choreography", () => {
  test("Beat 1 — all nine rows stream in and the footer ticks to the real stub counts", async ({
    page,
  }) => {
    await bootExtraction(page);

    // Nine rows, populated from /api/extract (the seven present values are visible).
    await expect(page.locator('[data-testid="field-row"]')).toHaveCount(9);
    await expect(row(page, "tumor_size_cm")).toContainText("1.4");
    await expect(row(page, "specimen")).toContainText("Left breast core biopsy");
    await expect(row(page, "her2_status")).toContainText("negative");

    // Footer = the actual stub total, NOT the illustrative §5.4 "6 grounded · 1 review" string.
    await expect(page.getByTestId("footer-counts")).toHaveText(PATH_COUNTS);
    await expect(page.getByTestId("footer-counts")).not.toContainText("review");
  });

  test("Beat 2 — THE GESTURE: hover tumor_size_cm washes its span at the API offsets", async ({
    page,
  }) => {
    await bootExtraction(page);
    const result = await fetchExtract(page, "path_report", "pathology");
    const samples = await (await page.request.get("/api/samples")).json();
    const docText = samples.find((s: any) => s.id === "path_report").text;
    const f = result.fields.find((x: any) => x.name === "tumor_size_cm");
    const expectedSpan = docText.slice(f.char_start, f.char_end);

    await row(page, "tumor_size_cm").hover();

    // The active mark exists and its text is EXACTLY the API offset slice (proof JS never re-grounds).
    const mark = page.locator("#ce-mark-active");
    await expect(mark).toBeVisible();
    await expect(mark).toHaveText(expectedSpan);
    expect(expectedSpan).toContain("1.4 cm");
  });

  test("Beat 3 — the first honest null: margin_status cites + washes cyan", async ({ page }) => {
    await bootExtraction(page);
    const result = await fetchExtract(page, "path_report", "pathology");
    const f = result.fields.find((x: any) => x.name === "margin_status");
    expect(f.value).toBeNull();
    expect(f.flag).toBe("not_assessed");
    // The cited-absence span DID ground (engine retains its offsets) → it can wash.
    expect(f.char_start).not.toBeNull();

    const r = row(page, "margin_status");
    await expect(r).toContainText("—"); // em-dash value
    await expect(r).toContainText("not assessed"); // text label, not just color
    await expect(r).toContainText("cites"); // the inline cited-absence caption

    await r.hover();
    const mark = page.locator("#ce-mark-active");
    await expect(mark).toBeVisible();
    await expect(mark).toHaveText("Margins not assessed on this specimen");
    // Cyan wash: the not_assessed flag color (#1593AB) drives the mark's left bar.
    const shadow = await mark.evaluate((el) => getComputedStyle(el).boxShadow);
    expect(shadow).toContain("21, 147, 171"); // rgb of #1593AB
  });

  test("Beat 4 — the second honest null: lymph_nodes_positive is silent (nothing washes)", async ({
    page,
  }) => {
    await bootExtraction(page);
    const result = await fetchExtract(page, "path_report", "pathology");
    const f = result.fields.find((x: any) => x.name === "lymph_nodes_positive");
    expect(f.value).toBeNull();
    expect(f.flag).toBe("not_found");
    expect(f.char_start).toBeNull(); // no span → nothing to wash

    const r = row(page, "lymph_nodes_positive");
    await expect(r).toContainText("—");
    await expect(r).toContainText("not found");
    await expect(r).toContainText("document is silent");

    await r.hover();
    // The document washes NOTHING for a not_found field — no active mark appears.
    await expect(page.locator("#ce-mark-active")).toHaveCount(0);
  });

  test("Beat 6 — the leaderboard: macro-F1, hallucination-rate 0, routing, per-field rows", async ({
    page,
  }) => {
    await bootExtraction(page);
    await page.getByRole("button", { name: "Eval", exact: true }).click();

    await expect(page.getByTestId("eval-halluc")).toHaveText("0");
    await expect(page.getByTestId("eval-macro-f1")).toHaveText("1.00");
    await expect(page.getByTestId("eval-routing")).toHaveText("1.00");
    // Per-field rows render from /api/eval (the frozen leaderboard).
    expect(await page.getByTestId("eval-row").count()).toBeGreaterThanOrEqual(9);
  });
});
