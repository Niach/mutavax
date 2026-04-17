/* eslint-disable @typescript-eslint/no-require-imports */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cancerstudioDesktop", {
  openPath: (targetPath) => ipcRenderer.invoke("desktop:open-path", targetPath),
  getAppDataPath: () => ipcRenderer.invoke("desktop:get-app-data-path"),
  getDataRoot: () => ipcRenderer.invoke("desktop:get-data-root"),
  notify: (payload) => ipcRenderer.invoke("desktop:notify", payload),
});
