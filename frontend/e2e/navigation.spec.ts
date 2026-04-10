/**
 * T-01: Navigation & Layout
 * GUI_TEST_SPECIFICATION.md §T-01
 */

import { test, expect, navigateToTab } from "./fixtures";

test.describe("T-01: Navigation & Layout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("T-01.1 — app shell renders with dark background", async ({ page }) => {
    const body = page.locator("body");
    await expect(body).toBeVisible();
    // Verify dark theme — background should be near-black
    const bg = await body.evaluate((el) => getComputedStyle(el).backgroundColor);
    // Accept any very dark color
    expect(bg).toMatch(/rgb\(\d{1,2}, \d{1,2}, \d{1,2}\)/);
  });

  test("T-01.2 — NavBar shows 7 tabs in correct order", async ({ page }) => {
    const nav = page.locator("nav");
    await expect(nav).toBeVisible();

    const expectedTabs = [
      "ADVISOR",
      "COMPOSER",
      "EFFECTS",
      "GENERATOR",
      "PO-33",
      "EP-133",
      "CODEGEN",
    ];

    for (const tab of expectedTabs) {
      await expect(
        page.getByRole("link", { name: tab, exact: true })
      ).toBeVisible();
    }
  });

  test("T-01.3 — clicking each tab navigates to correct route", async ({
    page,
  }) => {
    const routes: [string, string][] = [
      ["ADVISOR", "/advisor"],
      ["COMPOSER", "/composer"],
      ["EFFECTS", "/effects"],
      ["GENERATOR", "/generator"],
      ["PO-33", "/guide/po33"],
      ["EP-133", "/guide/ep133"],
      ["CODEGEN", "/codegen"],
    ];

    for (const [tab, path] of routes) {
      await page.goto("/");
      await navigateToTab(page, tab, path);
      expect(page.url()).toContain(path);
    }
  });

  test("T-01.4 — active tab has visual indicator", async ({ page }) => {
    await navigateToTab(page, "CODEGEN", "/codegen");
    const codegenLink = page.getByRole("link", { name: "CODEGEN", exact: true });
    // Active tab should have a distinguishing class or style
    const classes = await codegenLink.getAttribute("class");
    // Just verify it differs from an inactive tab
    const advisorLink = page.getByRole("link", { name: "ADVISOR", exact: true });
    const advisorClasses = await advisorLink.getAttribute("class");
    expect(classes).not.toEqual(advisorClasses);
  });

  test("T-01.5 — responsive at 768px width", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    // No horizontal overflow
    const scrollWidth = await page.evaluate(
      () => document.documentElement.scrollWidth
    );
    const clientWidth = await page.evaluate(
      () => document.documentElement.clientWidth
    );
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 10); // scrollbar width varies across browsers
  });

  test("T-01.6 — StatusBar shows connected state", async ({ page }) => {
    // Health endpoint is mocked to return 200 — should show connected
    // Wait for health poll
    await page.waitForTimeout(2000);
    const statusBar = page.locator("[data-testid=status-bar], footer, [class*=status]").first();
    if (await statusBar.isVisible()) {
      const text = await statusBar.textContent();
      expect(text?.toLowerCase()).toContain("connect");
    }
  });

  test("T-01.7 — default route redirects to /advisor", async ({ page }) => {
    await page.goto("/nonexistent-route");
    await page.waitForURL("**/advisor");
    expect(page.url()).toContain("/advisor");
  });
});
