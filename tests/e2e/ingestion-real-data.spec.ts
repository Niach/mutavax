import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "..", "..");
const apiBase = process.env.REAL_DATA_API_BASE ?? "http://127.0.0.1:8001";
const sampleDir =
  process.env.REAL_DATA_SAMPLE_DIR
    ? path.resolve(process.env.REAL_DATA_SAMPLE_DIR)
    : path.join(repoRoot, "data", "sample-data", "seqc2-hcc1395-wes-ll", "smoke");
const alignmentSampleDir =
  process.env.REAL_DATA_ALIGNMENT_SAMPLE_DIR
    ? path.resolve(process.env.REAL_DATA_ALIGNMENT_SAMPLE_DIR)
    : path.join(repoRoot, "data", "sample-data", "htslib-xx-pair", "smoke");

function samplePath(filename: string) {
  const filePath = path.join(sampleDir, filename);
  if (!fs.existsSync(filePath)) {
    throw new Error(
      `Missing real-data sample fixture: ${filePath}. Run npm run sample-data:smoke or set REAL_DATA_SAMPLE_DIR.`
    );
  }
  return filePath;
}

function alignmentSamplePath(filename: string) {
  const filePath = path.join(alignmentSampleDir, filename);
  if (!fs.existsSync(filePath)) {
    throw new Error(
      `Missing alignment smoke fixture: ${filePath}. Run npm run sample-data:alignment or set REAL_DATA_ALIGNMENT_SAMPLE_DIR.`
    );
  }
  return filePath;
}

function tempFastqPath(filename: string, contents: string) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "cancerstudio-fastq-"));
  const filePath = path.join(directory, filename);
  fs.writeFileSync(filePath, contents, "utf8");
  return filePath;
}

test("ingestion smoke with public SEQC2 FASTQs", async ({ page }) => {
  const stamp = Date.now();

  await page.goto("/");

  await page.getByTestId("workspace-species-human").click();
  await page.getByTestId("workspace-name-input").fill(`SEQC2 smoke ${stamp}`);

  await Promise.all([
    page.waitForURL(/\/workspaces\/[^/]+\/ingestion$/),
    page.getByTestId("workspace-create-submit").click(),
  ]);

  await page
    .getByTestId("tumor-lane-file-input")
    .setInputFiles([
      samplePath("tumor_R1.fastq.gz"),
      samplePath("tumor_R2.fastq.gz"),
    ]);

  await expect(page.getByTestId("tumor-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "ready"
  );
  await page.getByTestId("tumor-staging-start-upload").click();

  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "locked"
  );

  await page
    .getByTestId("normal-lane-file-input")
    .setInputFiles([
      samplePath("normal_R1.fastq.gz"),
      samplePath("normal_R2.fastq.gz"),
    ]);

  await expect(page.getByTestId("normal-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "ready"
  );
  await page.getByTestId("normal-staging-start-upload").click();

  await expect(page.getByTestId("normal-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "unlocked"
  );

  await page.getByTestId("tumor-preview-toggle").click();

  await expect(page.getByTestId("tumor-preview-panel")).toHaveAttribute(
    "data-phase",
    "ready"
  );
  await expect(page.getByTestId("tumor-preview-panel")).toContainText(
    "reads sampled"
  );
});

test("ingestion accumulates files across multiple picks before starting", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const workspaceResponse = await request.post(`${apiBase}/api/workspaces/`, {
    data: { display_name: `Stage twice ${stamp}`, species: "human" },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();

  await page.goto(`/workspaces/${workspace.id}/ingestion`);

  // First pick: only R1 — staging should report missing R2 and disable Start.
  await page
    .getByTestId("tumor-lane-file-input")
    .setInputFiles([samplePath("tumor_R1.fastq.gz")]);

  await expect(page.getByTestId("tumor-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "missing-r2"
  );
  await expect(
    page.getByTestId("tumor-staging-start-upload")
  ).toBeDisabled();
  await expect(page.getByTestId("tumor-staging-panel")).toContainText(
    "Add the matching R2 file"
  );

  // Second pick: R2 only — should accumulate, not replace, and enable Start.
  await page
    .getByTestId("tumor-lane-file-input")
    .setInputFiles([samplePath("tumor_R2.fastq.gz")]);

  await expect(page.getByTestId("tumor-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "ready"
  );
  await expect(
    page.getByTestId("tumor-staging-start-upload")
  ).toBeEnabled();

  await page.getByTestId("tumor-staging-start-upload").click();

  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
});

test("ingestion blocks single-end staging with paired-end requirement", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const r2OnlyFastq = tempFastqPath(
    "tumor_R2.fastq",
    "@tumor-r2\nCCCC\n+\n!!!!\n"
  );
  const workspaceResponse = await request.post(`${apiBase}/api/workspaces/`, {
    data: {
      display_name: `Invalid lane ${stamp}`,
      species: "human",
    },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();

  await page.goto(`/workspaces/${workspace.id}/ingestion`);

  await page.getByTestId("tumor-lane-file-input").setInputFiles([r2OnlyFastq]);

  // The lane stays in idle phase — no upload session was ever created — and
  // the staging panel surfaces the missing-R1 message inline.
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-lane-phase",
    "idle"
  );
  await expect(page.getByTestId("tumor-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "missing-r1"
  );
  await expect(page.getByTestId("tumor-staging-panel")).toContainText(
    "Add the matching R1 file"
  );
  await expect(
    page.getByTestId("tumor-staging-start-upload")
  ).toBeDisabled();
  await expect(page.locator("body")).not.toContainText("needs attention");
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

test("reset clears ingestion state", async ({ page }) => {
  const stamp = Date.now();
  const tumorR1 = tempFastqPath("tumor_R1.fastq", "@tumor-r1\nAAAA\n+\n!!!!\n");
  const tumorR2 = tempFastqPath("tumor_R2.fastq", "@tumor-r2\nCCCC\n+\n!!!!\n");
  const normalR1 = tempFastqPath("normal_R1.fastq", "@normal-r1\nGGGG\n+\n!!!!\n");
  const normalR2 = tempFastqPath("normal_R2.fastq", "@normal-r2\nTTTT\n+\n!!!!\n");

  await page.goto("/");
  await page.getByTestId("workspace-name-input").fill(`Reset smoke ${stamp}`);

  await Promise.all([
    page.waitForURL(/\/workspaces\/[^/]+\/ingestion$/),
    page.getByTestId("workspace-create-submit").click(),
  ]);

  await page
    .getByTestId("tumor-lane-file-input")
    .setInputFiles([tumorR1, tumorR2]);
  await page.getByTestId("tumor-staging-start-upload").click();
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );

  await page
    .getByTestId("normal-lane-file-input")
    .setInputFiles([normalR1, normalR2]);
  await page.getByTestId("normal-staging-start-upload").click();
  await expect(page.getByTestId("normal-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Reset" }).click();

  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "locked"
  );
  await expect(page.locator("body")).toContainText("0/4 outputs ready");
  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "empty"
  );
});

test("ingestion smoke with BAM and CRAM alignment containers", async ({ page }) => {
  const stamp = Date.now();

  await page.goto("/");
  await page.getByTestId("workspace-species-human").click();
  await page.getByTestId("workspace-name-input").fill(`Alignment smoke ${stamp}`);

  await Promise.all([
    page.waitForURL(/\/workspaces\/[^/]+\/ingestion$/),
    page.getByTestId("workspace-create-submit").click(),
  ]);

  await page
    .getByTestId("tumor-lane-file-input")
    .setInputFiles([alignmentSamplePath("tumor.bam")]);

  await expect(page.getByTestId("tumor-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "ready"
  );
  await page.getByTestId("tumor-staging-start-upload").click();

  await expect(page.getByTestId("tumor-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "locked"
  );

  await page
    .getByTestId("normal-lane-file-input")
    .setInputFiles([alignmentSamplePath("normal.cram")]);

  await expect(page.getByTestId("normal-staging-panel")).toHaveAttribute(
    "data-validation-state",
    "ready"
  );
  await page.getByTestId("normal-staging-start-upload").click();

  await expect(page.getByTestId("normal-lane-panel")).toHaveAttribute(
    "data-summary-status",
    "ready"
  );
  await expect(page.getByTestId("alignment-status-indicator")).toHaveAttribute(
    "data-state",
    "unlocked"
  );
  await expect(page.locator("body")).toContainText("4/4 outputs ready");
});
