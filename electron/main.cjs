/* eslint-disable @typescript-eslint/no-require-imports */
const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Notification,
  shell,
} = require("electron");
const { spawnSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

// ----------------------------------------------------------------------------
// Constants + helpers
// ----------------------------------------------------------------------------

const FRONTEND_URL =
  process.env.CANCERSTUDIO_FRONTEND_URL || "http://127.0.0.1:3000";
const BACKEND_URL =
  process.env.CANCERSTUDIO_BACKEND_URL || "http://127.0.0.1:8000";
const BACKEND_IMAGE =
  process.env.CANCERSTUDIO_IMAGE || "cancerstudio-backend:dev";
const CONTAINER_NAME =
  process.env.CANCERSTUDIO_CONTAINER || "cancerstudio-electron";
const DEFAULT_DATA_ROOT = path.join(os.homedir(), "cancerstudio-data");
const HEALTH_TIMEOUT_MS = 90_000;
const HEALTH_POLL_MS = 1_500;

const userPrefsPath = () => path.join(app.getPath("userData"), "config.json");

function readPrefs() {
  try {
    const raw = fs.readFileSync(userPrefsPath(), "utf-8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writePrefs(updates) {
  const current = readPrefs();
  const next = { ...current, ...updates };
  fs.mkdirSync(path.dirname(userPrefsPath()), { recursive: true });
  fs.writeFileSync(userPrefsPath(), JSON.stringify(next, null, 2), "utf-8");
  return next;
}

function dockerVersionAvailable() {
  const result = spawnSync("docker", ["--version"]);
  return result.status === 0;
}

function nvidiaRuntimeAvailable() {
  // `docker info` reports configured runtimes. nvidia-container-toolkit shows up
  // as the "nvidia" runtime once `nvidia-ctk runtime configure` has been run.
  const result = spawnSync("docker", ["info", "--format", "{{json .Runtimes}}"]);
  if (result.status !== 0) return false;
  return result.stdout.toString().includes("nvidia");
}

function platformInstallHint() {
  if (process.platform === "darwin") {
    return "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and start it before relaunching cancerstudio.";
  }
  if (process.platform === "win32") {
    return "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ (with WSL2 backend) and start it before relaunching cancerstudio.";
  }
  return [
    "Install Docker Engine and start it:",
    "  curl -fsSL https://get.docker.com | sudo bash",
    "  sudo usermod -aG docker $USER  # then log out + back in",
    "",
    "For GPU variant calling (optional), also install the NVIDIA Container Toolkit",
    "per https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html",
  ].join("\n");
}

// ----------------------------------------------------------------------------
// Docker preflight (blocking)
// ----------------------------------------------------------------------------

async function ensureDocker() {
  while (!dockerVersionAvailable()) {
    const choice = dialog.showMessageBoxSync({
      type: "error",
      title: "Docker is required",
      message: "cancerstudio runs its backend in Docker.",
      detail: platformInstallHint(),
      buttons: ["Re-check", "Quit"],
      defaultId: 0,
      cancelId: 1,
    });
    if (choice === 1) {
      app.quit();
      return false;
    }
  }
  return true;
}

// ----------------------------------------------------------------------------
// Data-root wizard (first run only)
// ----------------------------------------------------------------------------

async function ensureDataRoot() {
  const prefs = readPrefs();
  if (prefs.dataRoot && fs.existsSync(prefs.dataRoot)) {
    fs.mkdirSync(path.join(prefs.dataRoot, "inbox"), { recursive: true });
    return prefs.dataRoot;
  }

  const intro = dialog.showMessageBoxSync({
    type: "info",
    title: "Pick a folder for your cancerstudio data",
    message: "cancerstudio will store workspaces, references, and your inbox here.",
    detail:
      `The default is ${DEFAULT_DATA_ROOT}. You can pick a different folder if you ` +
      `want results on an external drive — but stick with the same folder across runs ` +
      `so your existing workspaces stay visible.`,
    buttons: [`Use ${DEFAULT_DATA_ROOT}`, "Pick a folder…", "Quit"],
    defaultId: 0,
    cancelId: 2,
  });

  if (intro === 2) {
    app.quit();
    return null;
  }

  let chosen;
  if (intro === 0) {
    chosen = DEFAULT_DATA_ROOT;
  } else {
    const result = dialog.showOpenDialogSync({
      title: "Pick a data folder for cancerstudio",
      defaultPath: os.homedir(),
      properties: ["openDirectory", "createDirectory"],
    });
    if (!result || result.length === 0) {
      app.quit();
      return null;
    }
    chosen = result[0];
  }

  fs.mkdirSync(path.join(chosen, "inbox"), { recursive: true });
  writePrefs({ dataRoot: chosen });
  return chosen;
}

// ----------------------------------------------------------------------------
// Backend container supervisor
// ----------------------------------------------------------------------------

let backendLogProcess = null;

function imageExistsLocally(image) {
  const result = spawnSync("docker", ["image", "inspect", image]);
  return result.status === 0;
}

function stopExistingContainer() {
  // Best-effort cleanup of any prior backend container. `docker rm -f` ignores
  // missing names.
  spawnSync("docker", ["rm", "-f", CONTAINER_NAME], { stdio: "ignore" });
}

function startBackendContainer(dataRoot) {
  stopExistingContainer();

  const dockerArgs = [
    "run",
    "-d",
    "--rm",
    "--name",
    CONTAINER_NAME,
    "-p",
    "127.0.0.1:8000:8000",
    "-v",
    `${dataRoot}:/app-data`,
    "-v",
    `${path.join(dataRoot, "inbox")}:/inbox`,
    "-e",
    "CANCERSTUDIO_APP_DATA_DIR=/app-data",
    "-e",
    "CANCERSTUDIO_INBOX_DIR=/inbox",
  ];

  if (process.platform === "linux" && nvidiaRuntimeAvailable()) {
    dockerArgs.push("--gpus", "all");
  }

  dockerArgs.push(BACKEND_IMAGE);

  const result = spawnSync("docker", dockerArgs, { encoding: "utf-8" });
  if (result.status !== 0) {
    throw new Error(
      `docker run failed (exit ${result.status}):\n${result.stderr || result.stdout}`
    );
  }

  // Tail logs in the background so they're visible in the Electron stdout.
  backendLogProcess = spawn("docker", ["logs", "-f", CONTAINER_NAME], {
    stdio: ["ignore", "inherit", "inherit"],
  });
}

async function waitForBackendHealth() {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(`${BACKEND_URL}/health`, (res) => {
        if (res.statusCode === 200) {
          res.resume();
          resolve(true);
        } else {
          res.resume();
          retryOrFail();
        }
      });
      req.on("error", retryOrFail);
      req.setTimeout(2_000, () => {
        req.destroy();
        retryOrFail();
      });
    };
    const retryOrFail = () => {
      if (Date.now() >= deadline) {
        reject(
          new Error(
            `Backend never responded on ${BACKEND_URL}/health within ${
              HEALTH_TIMEOUT_MS / 1000
            }s. Check docker logs ${CONTAINER_NAME}.`
          )
        );
      } else {
        setTimeout(attempt, HEALTH_POLL_MS);
      }
    };
    attempt();
  });
}

function shutdownBackend() {
  try {
    if (backendLogProcess && !backendLogProcess.killed) {
      backendLogProcess.kill();
    }
  } catch {
    // best-effort
  }
  backendLogProcess = null;
  // Synchronous so the container is gone before the process exits.
  spawnSync("docker", ["stop", CONTAINER_NAME], { stdio: "ignore" });
}

// ----------------------------------------------------------------------------
// Window
// ----------------------------------------------------------------------------

function createWindow() {
  const window = new BrowserWindow({
    width: 1520,
    height: 980,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#f3f0e8",
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  window.loadURL(FRONTEND_URL);
}

function showFatal(title, detail) {
  dialog.showErrorBox(title, detail);
}

// ----------------------------------------------------------------------------
// IPC
// ----------------------------------------------------------------------------

function registerIpc(dataRoot) {
  ipcMain.handle("desktop:open-path", async (_event, targetPath) => {
    if (!targetPath) return;
    // Fire-and-forget: on some Linux DEs shell.openPath()'s Promise never
    // resolves after the file opens, tripping Electron's IPC watchdog.
    shell.openPath(targetPath).catch(() => {});
  });

  ipcMain.handle("desktop:get-app-data-path", async () => app.getPath("userData"));

  ipcMain.handle("desktop:get-data-root", async () => dataRoot);

  ipcMain.handle("desktop:notify", async (_event, payload) => {
    if (!payload || typeof payload !== "object") return;
    const title = typeof payload.title === "string" ? payload.title : "cancerstudio";
    const body = typeof payload.body === "string" ? payload.body : "";
    if (!Notification.isSupported()) return;
    try {
      new Notification({ title, body, silent: false }).show();
    } catch {
      // Notifications are best-effort.
    }
  });
}

// ----------------------------------------------------------------------------
// Bootstrap
// ----------------------------------------------------------------------------

async function bootstrap() {
  if (!(await ensureDocker())) return;

  const dataRoot = await ensureDataRoot();
  if (!dataRoot) return;

  if (!imageExistsLocally(BACKEND_IMAGE)) {
    const choice = dialog.showMessageBoxSync({
      type: "info",
      title: "Backend image not found",
      message: `Docker image ${BACKEND_IMAGE} is not available locally.`,
      detail:
        `Pull or build it before launching the app:\n\n` +
        `  docker compose build       # for local dev\n` +
        `  docker pull ${BACKEND_IMAGE}\n\n` +
        `Then click Re-check.`,
      buttons: ["Re-check", "Quit"],
      defaultId: 0,
      cancelId: 1,
    });
    if (choice === 1 || !imageExistsLocally(BACKEND_IMAGE)) {
      app.quit();
      return;
    }
  }

  try {
    startBackendContainer(dataRoot);
  } catch (err) {
    showFatal("Failed to start backend", err.message || String(err));
    app.quit();
    return;
  }

  try {
    await waitForBackendHealth();
  } catch (err) {
    showFatal("Backend never came up", err.message || String(err));
    shutdownBackend();
    app.quit();
    return;
  }

  registerIpc(dataRoot);
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
}

app.whenReady().then(() => {
  void bootstrap();
});

app.on("window-all-closed", () => {
  shutdownBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  shutdownBackend();
});
