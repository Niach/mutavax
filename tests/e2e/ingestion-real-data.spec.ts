import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "..", "..");
const apiBase = process.env.REAL_DATA_API_BASE ?? "http://127.0.0.1:8001";
const sampleDir =
  process.env.REAL_DATA_SAMPLE_DIR
    ? path.resolve(process.env.REAL_DATA_SAMPLE_DIR)
    : path.join(repoRoot, "data", "sample-data", "seqc2-hcc1395-wes-ll", "smoke");

function samplePath(filename: string) {
  const filePath = path.join(sampleDir, filename);
  if (!fs.existsSync(filePath)) {
    throw new Error(
      `Missing ingestion smoke fixture: ${filePath}. Run npm run sample-data:smoke or set REAL_DATA_SAMPLE_DIR.`
    );
  }
  return filePath;
}

function selectedFile(filename: string) {
  const filePath = samplePath(filename);
  const stats = fs.statSync(filePath);
  return {
    path: filePath,
    name: path.basename(filePath),
    sizeBytes: stats.size,
    modifiedAtMs: stats.mtimeMs,
  };
}

async function installDesktopMock(
  page: Page,
  selections: Array<
    Array<{
      path: string;
      name: string;
      sizeBytes: number;
      modifiedAtMs: number;
    }>
  >
) {
  await page.addInitScript((queuedSelections) => {
    const queue = [...queuedSelections];
    window.cancerstudioDesktop = {
      pickSequencingFiles: async () => queue.shift() ?? [],
      openPath: async () => {},
      getAppDataPath: async () => "/tmp/cancerstudio",
    };
  }, selections);
}

test("desktop ingestion smoke reaches alignment-ready state", async ({ page }) => {
  const stamp = Date.now();
  await installDesktopMock(page, [
    [selectedFile("tumor_R1.fastq.gz"), selectedFile("tumor_R2.fastq.gz")],
    [selectedFile("normal_R1.fastq.gz"), selectedFile("normal_R2.fastq.gz")],
  ]);

  await page.goto("/");
  await page.getByTestId("workspace-species-human").click();
  await page.getByTestId("workspace-name-input").fill(`Desktop intake ${stamp}`);

  await Promise.all([
    page.waitForURL(/\/workspaces\/[^/]+\/ingestion$/),
    page.getByTestId("workspace-create-submit").click(),
  ]);

  await page.getByTestId("tumor-pick-files").click();
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );

  await page.getByTestId("normal-pick-files").click();

  await expect(page.getByTestId("normal-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "unlocked"
  );
  await expect(page.getByTestId("tumor-preview-panel")).toHaveAttribute(
    "data-phase",
    "ready"
  );
});

test("reset clears derived intake state", async ({ page }) => {
  const stamp = Date.now();
  await installDesktopMock(page, [
    [selectedFile("tumor_R1.fastq.gz"), selectedFile("tumor_R2.fastq.gz")],
  ]);

  await page.goto("/");
  await page.getByTestId("workspace-name-input").fill(`Desktop reset ${stamp}`);

  await Promise.all([
    page.waitForURL(/\/workspaces\/[^/]+\/ingestion$/),
    page.getByTestId("workspace-create-submit").click(),
  ]);

  await page.getByTestId("tumor-pick-files").click();
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Reset ingestion" }).click();

  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "locked"
  );
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "empty"
  );
});

test("header plus returns to the home workspace foyer", async ({ page, request }) => {
  const stamp = Date.now();
  const workspaceResponse = await request.post(`${apiBase}/api/workspaces/`, {
    data: { display_name: `Plus nav ${stamp}`, species: "human" },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();

  await page.goto(`/workspaces/${workspace.id}/ingestion`);
  await page.getByLabel("New workspace").click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("Workspaces")).toBeVisible();
  await expect(page.getByText(`Plus nav ${stamp}`)).toBeVisible();
});
