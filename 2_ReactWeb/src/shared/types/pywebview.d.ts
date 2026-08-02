import type { DesktopShellApi } from "./desktopShell";

export {};

declare global {
  interface Window {
    pywebview?: {
      api?: DesktopShellApi;
    };
  }
}
