/**
 * T-04: Effects Explorer
 * GUI_TEST_SPECIFICATION.md §T-04
 */

import { test, expect } from "./fixtures";

test.describe("T-04: Effects Explorer", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/effects");
  });

  test("T-04.1 — displays 10 effect blocks", async ({ page }) => {
    // Wait for effects data to load
    await expect(page.getByText(/noise.?floor/i).first()).toBeVisible({ timeout: 5000 });

    const blockNames = [
      "noise_floor", "bitcrusher", "filter", "saturation", "reverb",
      "delay", "spatial", "glitch", "compressor", "vinyl",
    ];

    for (const name of blockNames) {
      const re = new RegExp(name.replace("_", "[_ ]?"), "i");
      await expect(page.getByText(re).first()).toBeVisible();
    }
  });

  test("T-04.2 — blocks are in signal chain order", async ({ page }) => {
    await expect(page.getByText(/noise.?floor/i).first()).toBeVisible({ timeout: 5000 });

    const allText = await page.locator("main, [class*=content], [class*=effects]").first().textContent();
    if (!allText) return;

    const positions = [
      "noise", "bitcrusher", "filter", "saturation", "reverb",
      "delay", "spatial", "glitch", "compressor", "vinyl",
    ].map((name) => allText.toLowerCase().indexOf(name));

    // Each block should appear after the previous one
    for (let i = 1; i < positions.length; i++) {
      if (positions[i] !== -1 && positions[i - 1] !== -1) {
        expect(positions[i]).toBeGreaterThan(positions[i - 1]);
      }
    }
  });

  test("T-04.3 — expanding a block shows parameters", async ({ page }) => {
    await expect(page.getByText(/noise.?floor/i).first()).toBeVisible({ timeout: 5000 });

    // Click the first block to expand
    await page.getByText(/noise.?floor/i).first().click();

    // Should show parameter details
    await expect(page.getByText(/pink|noise_type|level/i).first()).toBeVisible({ timeout: 3000 });
  });
});
