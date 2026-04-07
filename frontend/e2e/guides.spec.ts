/**
 * T-06 & T-07: PO-33 and EP-133 Guide Tabs
 * GUI_TEST_SPECIFICATION.md §T-06, §T-07
 */

import { test, expect } from "./fixtures";

test.describe("T-06: PO-33 Guide", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/guide/po33");
  });

  test("T-06.1 — sequencer grid renders", async ({ page }) => {
    // Should have clickable step/pad elements
    await expect(
      page.locator("[class*=step], [class*=pad], [class*=grid], [class*=sequencer]").first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-06.2 — steps are clickable and toggle state", async ({ page }) => {
    const steps = page.locator("[class*=step], [class*=pad], button[class*=cell]");
    const count = await steps.count();
    if (count === 0) return;

    const firstStep = steps.first();
    const classBefore = await firstStep.getAttribute("class");
    await firstStep.click();
    const classAfter = await firstStep.getAttribute("class");
    // Class should change on toggle
    expect(classAfter).not.toEqual(classBefore);
  });

  test("T-06.3 — play button exists", async ({ page }) => {
    await expect(
      page.locator("button").filter({ hasText: /play|start|▶/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-06.4 — BPM control exists", async ({ page }) => {
    await expect(
      page.locator("input[type=range], [class*=bpm], [class*=tempo]").first()
    ).toBeVisible({ timeout: 5000 });
  });
});

test.describe("T-07: EP-133 Guide", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/guide/ep133");
  });

  test("T-07.1 — EP-133 guide renders with group layout", async ({ page }) => {
    await expect(
      page.locator("[class*=group], [class*=pad], [class*=grid]").first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-07.2 — pads are interactive", async ({ page }) => {
    const pads = page.locator("[class*=pad], button[class*=cell], [class*=step]");
    const count = await pads.count();
    if (count === 0) return;

    const firstPad = pads.first();
    const classBefore = await firstPad.getAttribute("class");
    await firstPad.click();
    const classAfter = await firstPad.getAttribute("class");
    expect(classAfter).not.toEqual(classBefore);
  });

  test("T-07.3 — play button exists", async ({ page }) => {
    await expect(
      page.locator("button").filter({ hasText: /play|start|▶/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });
});
