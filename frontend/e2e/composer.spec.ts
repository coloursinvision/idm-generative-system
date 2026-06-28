/**
 * T-03: Composer Tab
 */

import { test, expect } from "./fixtures";

test.describe("T-03: Composer Tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/composer");
  });

  test("T-03.1 — composer panel renders with description input", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await expect(input).toBeVisible();
  });

  test("T-03.2 — submit returns JSON config with reasoning", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await input.fill("Dark, cavernous reverb with bitcrushed clicks");

    const submitBtn = page.locator("button").filter({ hasText: /compose|submit|generate|send/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
    } else {
      await input.press("Enter");
    }

    // Config JSON should appear — look for generator name from mock response
    await expect(page.getByText(/noise_burst/).first()).toBeVisible({ timeout: 5000 });
  });

  test("T-03.3 — reasoning section is displayed", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await input.fill("Lo-fi tape warmth");
    const submitBtn = page.locator("button").filter({ hasText: /compose|submit|generate|send/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
    } else {
      await input.press("Enter");
    }

    // Reasoning is a top-level field (ComposeResponse.reasoning) rendered in its own
    // panel. Backend contract aligned 2026-06-18 — knowledge/rag.py compose() now lifts
    // reasoning out of config to the top level (code review M2/M3).
    await expect(page.getByText(/long hall decay/i).first()).toBeVisible({ timeout: 5000 });
  });
});