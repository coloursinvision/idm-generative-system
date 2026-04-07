/**
 * T-02: Advisor Tab
 * GUI_TEST_SPECIFICATION.md §T-02
 */

import { test, expect } from "./fixtures";

test.describe("T-02: Advisor Tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/advisor");
  });

  test("T-02.1 — advisor panel renders with input field", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await expect(input).toBeVisible();
  });

  test("T-02.2 — can type question", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await input.fill("How does the TB-303 acid slide work?");
    await expect(input).toHaveValue("How does the TB-303 acid slide work?");
  });

  test("T-02.3 — submit returns answer with sources", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await input.fill("How does the TB-303 acid slide work?");

    // Submit via button or Enter
    const submitBtn = page.locator("button").filter({ hasText: /ask|submit|send/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
    } else {
      await input.press("Enter");
    }

    // Wait for answer text (not textarea — use the response container)
    await expect(page.getByText(/portamento circuit/).first()).toBeVisible({ timeout: 5000 });
    // Sources should be visible
    await expect(page.getByText(/Part 4\.2/).first()).toBeVisible();
  });

  test("T-02.4 — answer contains relevant content", async ({ page }) => {
    const input = page.locator("textarea, input[type=text]").first();
    await input.fill("acid slide");
    const submitBtn = page.locator("button").filter({ hasText: /ask|submit|send/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
    } else {
      await input.press("Enter");
    }

    await expect(page.getByText(/portamento circuit/).first()).toBeVisible({ timeout: 5000 });
  });
});
