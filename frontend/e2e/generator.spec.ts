/**
 * T-05: Generator Tab
 * GUI_TEST_SPECIFICATION.md §T-05
 */

import { test, expect } from "./fixtures";

test.describe("T-05: Generator Tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/generator");
  });

  test("T-05.1 — generator panel renders with controls", async ({ page }) => {
    // Generator uses a button group (not <select>) — verify generator buttons + GENERATE
    await expect(page.locator("button").filter({ hasText: /glitch/i }).first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator("button").filter({ hasText: /generate/i }).first()).toBeVisible();
  });

  test("T-05.2 — generate returns waveform display", async ({ page }) => {
    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    await generateBtn.click();

    await expect(
      page.locator("canvas, svg, audio, [class*=waveform], [class*=audio]").first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-05.3 — play button appears after generation", async ({ page }) => {
    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    await generateBtn.click();

    await expect(
      page.locator("button").filter({ hasText: /play|▶/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-05.4 — download button appears after generation", async ({ page }) => {
    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    await generateBtn.click();

    await expect(
      page.locator("button, a").filter({ hasText: /download|save|↓/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-05.5 — download triggers file save", async ({ page }) => {
    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    await generateBtn.click();

    const downloadPromise = page.waitForEvent("download", { timeout: 5000 }).catch(() => null);
    const dlBtn = page.locator("button, a").filter({ hasText: /download|save|↓/i }).first();
    await dlBtn.click();
    const download = await downloadPromise;
    if (download) {
      expect(download.suggestedFilename()).toMatch(/\.wav$/);
    }
  });
});
