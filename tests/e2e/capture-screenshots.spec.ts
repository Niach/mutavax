/**
 * Dev utility: capture fresh screenshots of the app into docs/screenshots/.
 *
 * Assumes backend is running at http://127.0.0.1:8000 with the real
 * COLO829 workspace in the DB, and frontend is at http://127.0.0.1:3000.
 *
 * Run with:
 *   npx playwright test tests/e2e/capture-screenshots.spec.ts --workers=1
 *
 * Not part of the default test suite — matches the --grep pattern only
 * when explicitly invoked.
 */
import path from "node:path";
import fs from "node:fs";

import { test, expect, type Page } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "..", "..");
const outDir = path.join(repoRoot, "docs", "screenshots");
const workspaceId = "c0653476-a18e-465d-a8c0-11b52e5b9752";

fs.mkdirSync(outDir, { recursive: true });

async function waitForContent(page: Page, marker: string) {
  await expect(page.getByText(marker, { exact: false }).first()).toBeVisible({
    timeout: 30_000,
  });
}

test.beforeEach(async ({ page }) => {
  // Silence any page error popups from desktop bridge absence
  await page.addInitScript(() => {
    (window as unknown as { cancerstudioDesktop?: unknown }).cancerstudioDesktop = {
      openPath: async () => {},
      getAppDataPath: async () => "",
      getDataRoot: async () => "",
    };
  });
});

test("capture landing (workspaces list)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto("http://127.0.0.1:3000/");
  await waitForContent(page, "COLO829 100x reference run");
  await page.screenshot({
    path: path.join(outDir, "landing.png"),
    clip: { x: 0, y: 0, width: 1440, height: 720 },
  });
});

test("capture ingestion stage", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`http://127.0.0.1:3000/workspaces/${workspaceId}/ingestion`);
  await waitForContent(page, "COLO829 100x reference run");
  // Give the panel a moment to hydrate the lane previews
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: path.join(outDir, "ingestion.png"),
    clip: { x: 0, y: 0, width: 1440, height: 820 },
  });
});

test("capture alignment stage (completed)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto(`http://127.0.0.1:3000/workspaces/${workspaceId}/alignment`);
  await waitForContent(page, "Alignment quality");
  // Expand the quality details so the QC metrics are in frame
  const qualityToggle = page.getByRole("button", { name: /Show quality details/i });
  if (await qualityToggle.isVisible()) {
    await qualityToggle.click();
  }
  await page.waitForTimeout(800);
  await page.screenshot({
    path: path.join(outDir, "alignment.png"),
    clip: { x: 0, y: 0, width: 1440, height: 1000 },
  });
});

test("capture variant calling stage (preview)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    `http://127.0.0.1:3000/workspaces/${workspaceId}/variant-calling`
  );
  await waitForContent(page, "Somatic variant calling");
  await page.waitForTimeout(800);
  await page.screenshot({
    path: path.join(outDir, "variant-calling.png"),
    clip: { x: 0, y: 0, width: 1440, height: 720 },
  });
});
