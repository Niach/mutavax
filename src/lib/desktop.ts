export interface DesktopNotifyPayload {
  title: string;
  body: string;
}

export interface DesktopBridge {
  openPath: (targetPath: string) => Promise<void>;
  getAppDataPath: () => Promise<string>;
  getDataRoot: () => Promise<string>;
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
