/**
 * interactions.spec.ts (Split 08) — pin / JSON / schema-switch interactions over the live stub stack.
 */
import { test, expect } from "@playwright/test";
import { bootExtraction, switchSample, row, INTAKE_COUNTS } from "./helpers";

test.describe("interactions", () => {
  test("click-to-pin keeps a span lit and highlights the row; multiple pins coexist", async ({
    page,
  }) => {
    await bootExtraction(page);

    // Pin tumor_size_cm by clicking; its span stays marked even after the pointer moves away.
    await row(page, "tumor_size_cm").click();
    await page.mouse.move(0, 0);
    await expect(page.locator("#ce-doc mark")).toHaveCount(1);

    // Reciprocal: the pinned row carries the active background tint (#F4F6F9).
    await expect(row(page, "tumor_size_cm")).toHaveCSS("background-color", "rgb(244, 246, 249)");

    // Pin a second field — both spans light up together.
    await row(page, "er_status").click();
    await page.mouse.move(0, 0);
    await expect(page.locator("#ce-doc mark")).toHaveCount(2);
  });

  test("JSON toggle reveals the real ExtractionResult with char offsets", async ({ page }) => {
    await bootExtraction(page);
    await page.getByRole("button", { name: "JSON", exact: true }).click();

    const json = page.getByTestId("json-inspector");
    await expect(json).toBeVisible();
    const text = await json.innerText();
    const parsed = JSON.parse(text);
    // The raw engine result — real integer offsets, not recomputed in JS.
    const tumor = parsed.fields.find((f: any) => f.name === "tumor_size_cm");
    expect(Number.isInteger(tumor.char_start)).toBeTruthy();
    expect(Number.isInteger(tumor.char_end)).toBeTruthy();
    expect(parsed.schema_version).toBe("v2");
  });

  test("schema/sample switch re-extracts: intake shows the ListField + pcp not_found", async ({
    page,
  }) => {
    await bootExtraction(page);
    await switchSample(page, "Intake");

    // The medications ListField is flattened to name[i] rows.
    await expect(row(page, "medications[0]")).toContainText("Lisinopril");
    await expect(row(page, "medications[1]")).toContainText("Metformin");
    await expect(row(page, "medications[2]")).toContainText("Atorvastatin");

    // pcp is a genuine not_found null.
    const pcp = row(page, "pcp");
    await expect(pcp).toContainText("—");
    await expect(pcp).toContainText("not found");

    // Footer reflects the intake totals (8 grounded · 1 null · 1 review).
    await expect(page.getByTestId("footer-counts")).toHaveText(INTAKE_COUNTS);

    // Switching back to pathology re-extracts the original nine fields.
    await switchSample(page, "Pathology");
    await expect(row(page, "tumor_size_cm")).toContainText("1.4");
  });
});
