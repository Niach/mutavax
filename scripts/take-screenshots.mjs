#!/usr/bin/env node
/**
 * Regenerate every PNG under docs/screenshots/ from the live dev server.
 *
 * Usage:
 *   node scripts/take-screenshots.mjs [workspaceId]
 *
 * Requires the frontend (:3000) and backend (:8000) to be running. For
 * stages 1–5 the target workspace must have completed those runs for real.
 * For stages 6–8 alone, you can seed a synthetic workspace via:
 *     docker exec cancerstudio-backend python /tmp/seed.py
 * (copy `scripts/seed_demo_workspace.py` into the container first).
 * Pass `--stages=7,8` to only capture specific stages.
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const FRONTEND = "http://localhost:3000";
const BACKEND = "http://127.0.0.1:8000";
const argv = process.argv.slice(2);
const stageFilter = argv.find((a) => a.startsWith("--stages="))?.split("=")[1];
const positional = argv.filter((a) => !a.startsWith("--"));
const WORKSPACE_ID = positional[0] || "73502c7e-41e7-4407-ae9a-9015bbf91efa";
const OUT_DIR = resolve("docs/screenshots");
const VIEWPORT = { width: 1600, height: 1000 };
const SCALE = 2;
const SETTLE_MS = 2000;

const allPages = [
  { name: "landing.png", path: "/", stage: "0" },
  { name: "new-workspace.png", path: "/workspaces/new", stage: "0" },
  { name: "ingestion.png", path: `/workspaces/${WORKSPACE_ID}/ingestion`, stage: "1" },
  { name: "alignment.png", path: `/workspaces/${WORKSPACE_ID}/alignment`, stage: "2" },
  { name: "variant-calling.png", path: `/workspaces/${WORKSPACE_ID}/variant-calling`, stage: "3" },
  { name: "annotation.png", path: `/workspaces/${WORKSPACE_ID}/annotation`, stage: "4" },
  { name: "neoantigen.png", path: `/workspaces/${WORKSPACE_ID}/neoantigen-prediction`, stage: "5" },
  { name: "epitope-selection.png", path: `/workspaces/${WORKSPACE_ID}/epitope-selection`, stage: "6" },
  { name: "construct-design.png", path: `/workspaces/${WORKSPACE_ID}/construct-design`, stage: "7" },
  { name: "construct-output.png", path: `/workspaces/${WORKSPACE_ID}/construct-output`, stage: "8" },
];

const wantedStages = stageFilter
  ? new Set(stageFilter.split(",").map((s) => s.trim()))
  : null;
const pages = wantedStages
  ? allPages.filter((p) => wantedStages.has(p.stage))
  : allPages;

async function probe(url, label) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.error(`\n✖ ${label} is not reachable at ${url}: ${err.message}`);
    console.error(`  Start it with \`npm run dev:all\` and retry.\n`);
    process.exit(1);
  }
}

async function main() {
  await probe(FRONTEND, "Frontend dev server");
  await probe(`${BACKEND}/api/workspaces/`, "Backend API");

  mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_BIN || "/usr/bin/chromium",
  });
  const ctx = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
  });
  const page = await ctx.newPage();

  page.on("pageerror", (e) => console.error(`   page error: ${e.message}`));

  for (const spec of pages) {
    const url = `${FRONTEND}${spec.path}`;
    const out = resolve(OUT_DIR, spec.name);
    console.log(`→ ${spec.name}   ${url}`);
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    } catch (err) {
      console.error(`   nav failed (${err.message}); falling back to domcontentloaded`);
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    }
    await page.waitForTimeout(SETTLE_MS);
    await page.screenshot({ path: out, fullPage: true });
    console.log(`   saved ${out}`);
  }

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
