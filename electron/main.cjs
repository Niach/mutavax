/* eslint-disable @typescript-eslint/no-require-imports */
const { app, BrowserWindow, dialog, ipcMain, Notification, shell } = require("electron");
const { statSync } = require("node:fs");
const { join } = require("node:path");

const FRONTEND_URL =
  process.env.CANCERSTUDIO_FRONTEND_URL || "http://127.0.0.1:3000";

function createWindow() {
  const window = new BrowserWindow({
    width: 1520,
    height: 980,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#f3f0e8",
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  window.loadURL(FRONTEND_URL);
}

app.whenReady().then(() => {
  ipcMain.handle("desktop:pick-sequencing-files", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose sequencing files",
      properties: ["openFile", "multiSelections"],
      filters: [
        {
          name: "Sequencing files",
          extensions: ["fastq", "fq", "gz", "bam", "cram"],
        },
      ],
    });

    if (result.canceled) {
      return [];
    }

    return result.filePaths.map((filePath) => {
      const stats = statSync(filePath);
      return {
        path: filePath,
        name: filePath.split(/[\\/]/).pop() || filePath,
        sizeBytes: stats.size,
        modifiedAtMs: Math.round(stats.mtimeMs),
      };
    });
  });

  ipcMain.handle("desktop:open-path", async (_event, targetPath) => {
    if (!targetPath) {
      return;
    }
    // Fire-and-forget: on some Linux desktop environments shell.openPath()'s
    // Promise never resolves after the file opens successfully, tripping
    // Electron's "reply was never sent" IPC watchdog.
    shell.openPath(targetPath).catch(() => {});
  });

  ipcMain.handle("desktop:get-app-data-path", async () => app.getPath("userData"));

  ipcMain.handle("desktop:notify", async (_event, payload) => {
    if (!payload || typeof payload !== "object") return;
    const title = typeof payload.title === "string" ? payload.title : "cancerstudio";
    const body = typeof payload.body === "string" ? payload.body : "";
    if (!Notification.isSupported()) return;
    try {
      new Notification({ title, body, silent: false }).show();
    } catch {
      // Swallow — notifications are best-effort.
    }
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
