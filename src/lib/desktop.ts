export interface DesktopSelectedFile {
  path: string;
  name: string;
  sizeBytes: number;
  modifiedAtMs: number;
}

export interface DesktopNotifyPayload {
  title: string;
  body: string;
}

export interface DesktopBridge {
  pickSequencingFiles: () => Promise<DesktopSelectedFile[]>;
  openPath: (targetPath: string) => Promise<void>;
  getAppDataPath: () => Promise<string>;
  notify?: (payload: DesktopNotifyPayload) => Promise<void>;
}

declare global {
  interface Window {
    cancerstudioDesktop?: DesktopBridge;
  }
}

export function getDesktopBridge(): DesktopBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.cancerstudioDesktop ?? null;
}

export function isDesktopRuntime() {
  return getDesktopBridge() !== null;
}
