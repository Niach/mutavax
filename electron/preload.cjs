/* eslint-disable @typescript-eslint/no-require-imports */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("cancerstudioDesktop", {
  pickSequencingFiles: () => ipcRenderer.invoke("desktop:pick-sequencing-files"),
  openPath: (targetPath) => ipcRenderer.invoke("desktop:open-path", targetPath),
  getAppDataPath: () => ipcRenderer.invoke("desktop:get-app-data-path"),
  notify: (payload) => ipcRenderer.invoke("desktop:notify", payload),
});
