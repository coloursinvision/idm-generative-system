/**
 * T-12: Error States + T-13: Console Audit
 * GUI_TEST_SPECIFICATION.md §T-12, §T-13
 */

import { test as base, expect, type Page } from "@playwright/test";

/* ================================================================== */
/* T-12: Error States (uses custom mocks, not auto-mock fixture)       */
/* ================================================================== */

base.describe("T-12: Error States", () => {
  base.beforeEach(async ({ page }) => {
    // Mock all routes to fail (simulating backend down)
    await page.route("**/api/**", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Service unavailable" }) })
    );
  });

  base.test("T-12.1 — advisor shows error on backend failure", async ({ page }) => {
    await page.goto("/advisor");
    const input = page.locator("textarea, input[type=text]").first();
    if (!(await input.isVisible({ timeout: 3000 }).catch(() => false))) return;

    await input.fill("test question");
    const submitBtn = page.locator("button").filter({ hasText: /ask|submit|send/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
    } else {
      await input.press("Enter");
    }

    // Should show error message, not crash
    await expect(page.getByText(/error|failed|unavailable/i).first()).toBeVisible({ timeout: 5000 });
  });

  base.test("T-12.2 — codegen shows error on backend failure", async ({ page }) => {
    await page.goto("/codegen");

    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    if (!(await generateBtn.isVisible({ timeout: 3000 }).catch(() => false))) return;

    await generateBtn.click();

    // Should show error, not unhandled rejection
    await expect(page.getByText(/error|failed|unavailable/i).first()).toBeVisible({ timeout: 5000 });
  });

  base.test("T-12.3 — generator shows error on backend failure", async ({ page }) => {
    await page.goto("/generator");

    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    if (!(await generateBtn.isVisible({ timeout: 3000 }).catch(() => false))) return;

    await generateBtn.click();

    await expect(page.getByText(/error|failed|unavailable/i).first()).toBeVisible({ timeout: 5000 });
  });

  base.test("T-12.4 — no unhandled promise rejections on failure", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/codegen");
    const generateBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    if (await generateBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await generateBtn.click();
      await page.waitForTimeout(2000);
    }

    // Filter out known acceptable errors
    const critical = errors.filter(
      (e) => !e.includes("ResizeObserver") && !e.includes("chunk")
    );
    expect(critical).toHaveLength(0);
  });
});

/* ================================================================== */
/* T-13: Console Audit (uses working mocks)                            */
/* ================================================================== */

import { test } from "./fixtures";

test.describe("T-13: Console Audit", () => {
  test("T-13.1 — no console.error on initial load of each tab", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    const routes = [
      "/advisor", "/composer", "/effects", "/generator",
      "/guide/po33", "/guide/ep133", "/codegen",
    ];

    for (const route of routes) {
      await page.goto(route);
      await page.waitForTimeout(1000);
    }

    // Filter known benign errors (React strict mode, dev warnings)
    const real = errors.filter(
      (e) =>
        !e.includes("Warning:") &&
        !e.includes("ResizeObserver") &&
        !e.includes("DevTools")
    );
    expect(real).toHaveLength(0);
  });

  test("T-13.2 — rapid tab navigation produces no errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/advisor");

    const tabs = ["COMPOSER", "EFFECTS", "GENERATOR", "CODEGEN", "ADVISOR", "CODEGEN", "EFFECTS"];
    for (const tab of tabs) {
      await page.getByRole("link", { name: tab, exact: true }).click();
      await page.waitForTimeout(200);
    }

    const critical = errors.filter((e) => !e.includes("ResizeObserver"));
    expect(critical).toHaveLength(0);
  });

  test("T-13.3 — no pageerror exceptions during codegen flow", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/codegen");
    const genBtn = page.locator("button").filter({ hasText: /generate/i }).first();
    await genBtn.click();
    await page.waitForTimeout(2000);

    // Switch target
    await page.getByText(/\bTIDAL\b/).first().click();
    await genBtn.click();
    await page.waitForTimeout(2000);

    const critical = errors.filter((e) => !e.includes("ResizeObserver"));
    expect(critical).toHaveLength(0);
  });
});
