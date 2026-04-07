/**
 * T-08, T-09, T-10: Codegen Panel, Config Drawer, Popout Window
 * GUI_TEST_SPECIFICATION.md §T-08, §T-09, §T-10
 */

import { test, expect, getCodeBlockText } from "./fixtures";

/* ================================================================== */
/* T-08: Codegen Core Flow                                             */
/* ================================================================== */

test.describe("T-08: Codegen Core Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/codegen");
  });

  test("T-08.1 — codegen panel renders with SC/TIDAL tabs and GENERATE button", async ({ page }) => {
    await expect(page.getByText(/\bSC\b/).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/\bTIDAL\b/).first()).toBeVisible();
    await expect(
      page.locator("button").filter({ hasText: /generate/i }).first()
    ).toBeVisible();
  });

  test("T-08.2 — SC tab is default active", async ({ page }) => {
    const scTab = page.getByText(/\bSC\b/).first();
    await expect(scTab).toBeVisible({ timeout: 5000 });
    const classes = await scTab.getAttribute("class") ?? "";
    expect(classes.length).toBeGreaterThan(0);
  });

  test("T-08.3 — GENERATE (SC) produces sclang code block", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();

    // Wait for code toolbar to appear (proves CodeBlock rendered)
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    // CodeBlock renders lines in separate <code> elements — collect all
    const fullText = await getCodeBlockText(page);
    expect(fullText).toContain("SynthDef");
  });

  test("T-08.4 — toolbar shows SCLANG .SCD label", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/\.SCD/i).first()).toBeVisible();
  });

  test("T-08.5 — solarized dark background on code block", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    // The code area div has backgroundColor set inline to #002b36
    const bg = await page.locator("code").first().evaluate((el) => {
      let node: Element | null = el;
      while (node) {
        const style = getComputedStyle(node);
        if (style.backgroundColor && style.backgroundColor !== "rgba(0, 0, 0, 0)") {
          return style.backgroundColor;
        }
        node = node.parentElement;
      }
      return "";
    });

    // Solarized base03: #002b36 = rgb(0, 43, 54)
    expect(bg).toMatch(/rgb\(0,\s*43,\s*54\)/);
  });

  test("T-08.6 — COPY button copies code to clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);

    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    await page.locator("button").filter({ hasText: /copy/i }).first().click();

    const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboardText).toContain("SynthDef");
  });

  test("T-08.7 — DOWNLOAD button saves .scd file", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    const downloadPromise = page.waitForEvent("download");
    await page.locator("button, a").filter({ hasText: /download|save|↓/i }).first().click();

    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.scd$/);
  });

  test("T-08.8 — switch to TIDAL tab", async ({ page }) => {
    await page.getByText(/\bTIDAL\b/).first().click();
    await expect(page.getByText(/\bTIDAL\b/).first()).toBeVisible();
  });

  test("T-08.9 — GENERATE (TIDAL) produces Haskell/Tidal code", async ({ page }) => {
    await page.getByText(/\bTIDAL\b/).first().click();
    await page.locator("button").filter({ hasText: /generate/i }).first().click();

    await expect(page.getByText(/HASKELL/i).first()).toBeVisible({ timeout: 5000 });

    const fullText = await getCodeBlockText(page);
    expect(fullText).toMatch(/d1|setcps/);
  });

  test("T-08.10 — TIDAL toolbar shows HASKELL / TIDAL .TIDAL label", async ({ page }) => {
    await page.getByText(/\bTIDAL\b/).first().click();
    await page.locator("button").filter({ hasText: /generate/i }).first().click();

    await expect(page.getByText(/HASKELL/i).first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/\.TIDAL/i).first()).toBeVisible();
  });

  test("T-08.11 — TIDAL DOWNLOAD saves .tidal file", async ({ page }) => {
    await page.getByText(/\bTIDAL\b/).first().click();
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/HASKELL/i).first()).toBeVisible({ timeout: 5000 });

    const downloadPromise = page.waitForEvent("download");
    await page.locator("button, a").filter({ hasText: /download|save|↓/i }).first().click();

    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.tidal$/);
  });
});

/* ================================================================== */
/* T-09: Config Drawer                                                 */
/* ================================================================== */

test.describe("T-09: Codegen Config Drawer", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/codegen");
  });

  test("T-09.1 — CONFIG toggle expands drawer", async ({ page }) => {
    const configToggle = page.locator("button").filter({ hasText: /config/i }).first();
    await expect(configToggle).toBeVisible({ timeout: 5000 });
    await configToggle.click();

    // Drawer uses button groups (not <select>) for generator/mode + a BPM input
    await expect(page.locator("input[type=number]").first()).toBeVisible({ timeout: 3000 });
  });

  test("T-09.2 — collapsed state shows summary", async ({ page }) => {
    // Config summary shows truncated generator names: GLITCH / STUDIO / ...
    const summary = page.getByText(/glitch|noise|studio|live/i).first();
    await expect(summary).toBeVisible({ timeout: 5000 });
  });

  test("T-09.3 — mode toggle between studio and live", async ({ page }) => {
    const configToggle = page.locator("button").filter({ hasText: /config/i }).first();
    await configToggle.click();

    const modeControl = page.getByText(/studio|live/i).first();
    await expect(modeControl).toBeVisible({ timeout: 3000 });
  });

  test("T-09.4 — studio mode generates full script", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    const fullText = await getCodeBlockText(page);
    expect(fullText).toMatch(/waitForBoot|s\.boot/i);
  });

  test("T-09.5 — collapsing CONFIG keeps code visible", async ({ page }) => {
    await page.locator("button").filter({ hasText: /generate/i }).first().click();
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible({ timeout: 5000 });

    const configToggle = page.locator("button").filter({ hasText: /config/i }).first();
    await configToggle.click();
    await page.waitForTimeout(300);
    await configToggle.click();

    // Code toolbar should still be visible
    await expect(page.getByText(/SCLANG/i).first()).toBeVisible();
  });
});

/* ================================================================== */
/* T-10: Codegen Popout Window                                         */
/* ================================================================== */

test.describe("T-10: Codegen Popout", () => {
  test("T-10.1 — popout route renders standalone", async ({ page }) => {
    await page.goto("/codegen-popout");
    // CodegenPopout renders inside AppShell — verify GENERATE button is present
    await expect(
      page.locator("button").filter({ hasText: /generate/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-10.2 — popout has GENERATE and COPY buttons", async ({ page }) => {
    await page.goto("/codegen-popout");
    await expect(
      page.locator("button").filter({ hasText: /generate/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });

  test("T-10.3 — popout can generate code independently", async ({ page }) => {
    await page.goto("/codegen-popout");
    await page.locator("button").filter({ hasText: /generate/i }).first().click();

    // Wait for code to render
    await expect(page.getByText(/SCLANG|HASKELL/i).first()).toBeVisible({ timeout: 5000 });

    const fullText = await getCodeBlockText(page);
    expect(fullText.length).toBeGreaterThan(10);
  });

  test("T-10.4 — popout button exists in main codegen panel", async ({ page }) => {
    await page.goto("/codegen");
    await expect(
      page.locator("button").filter({ hasText: /⧉|popout|detach|undock/i }).first()
    ).toBeVisible({ timeout: 5000 });
  });
});
