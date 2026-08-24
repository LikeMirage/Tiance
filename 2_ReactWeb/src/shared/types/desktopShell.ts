export interface WindowBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type NativeWindowResizeEdge =
  | "top"
  | "right"
  | "bottom"
  | "left"
  | "top-left"
  | "top-right"
  | "bottom-right"
  | "bottom-left";

export interface DesktopShellState {
  available: boolean;
  frameless: boolean;
  maximized: boolean;
  minWidth: number;
  minHeight: number;
}

export interface WindowStateSnapshot {
  frameless: boolean;
  maximized: boolean;
  minWidth: number;
  minHeight: number;
}

export interface DesktopShellCapabilities {
  nativeWindowDragSupported: boolean;
  nativeWindowResizeMode: NativeWindowResizeMode;
  nativeWindowResizeSupported: boolean;
  pageZoomSupported: boolean;
  platform: string;
  systemTraySupported: boolean;
}

export type NativeWindowResizeMode = "none" | "api" | "system-edge";

export interface PageZoomSnapshot {
  available: boolean;
  zoomFactor: number;
}

export type DesktopPathEntry = {
  kind: "file" | "folder";
  name: string;
  path: string;
};

export type DesktopExternalFileImportFailureReason =
  | "source_missing"
  | "copy_failed";

export type DesktopExternalFileImportResult = {
  failures: Array<{
    name: string;
    reason: DesktopExternalFileImportFailureReason;
    sourcePath: string;
  }>;
  imported: Array<{
    name: string;
    path: string;
    sourcePath: string;
  }>;
};

export interface SystemMetricsProcessSnapshot {
  cpuPercent: number;
  memoryBytes: number;
  name: string;
  pid: number;
}

export interface SystemMetricsSnapshot {
  app?: {
    cpuPercent: number;
    memoryBytes: number;
    processCount: number;
  };
  available: boolean;
  processes?: SystemMetricsProcessSnapshot[];
  reason?: string;
  sampledAt: string;
  system?: {
    cpuPercent: number;
    memoryAvailableBytes: number;
    memoryPercent: number;
    memoryTotalBytes: number;
    memoryUsedBytes: number;
  };
}

export interface DesktopShellApi {
  reveal_window?: () => Promise<boolean> | boolean;
  minimize_window: () => Promise<void>;
  hide_window_to_tray?: () => Promise<boolean> | boolean;
  toggle_maximize_window: () => Promise<WindowStateSnapshot>;
  close_window: () => Promise<void>;
  install_software_update?: (stagePath: string) => Promise<{
    ok: boolean;
    errorCode: string;
    error: string;
  }>;
  get_window_state: () => Promise<WindowStateSnapshot>;
  get_shell_capabilities?: () => Promise<DesktopShellCapabilities>;
  get_window_bounds: () => Promise<WindowBounds>;
  get_clipboard_path_entries?: () => Promise<DesktopPathEntry[]>;
  select_external_files?: () => Promise<DesktopPathEntry[]>;
  set_clipboard_path_entries?: (paths: string[]) => Promise<boolean>;
  copy_external_entries_to_directory?: (
    sourcePaths: string[],
    destinationRoot: string,
  ) => Promise<DesktopExternalFileImportResult>;
  open_external_url?: (url: string) => Promise<boolean>;
  get_page_zoom_factor?: () => Promise<PageZoomSnapshot>;
  get_system_metrics?: () => Promise<SystemMetricsSnapshot>;
  set_page_zoom_factor?: (zoomFactor: number) => Promise<PageZoomSnapshot>;
  set_window_bounds: (x: number, y: number, width: number, height: number) => Promise<boolean>;
  move_window: (x: number, y: number) => Promise<boolean>;
  start_window_drag?: (
    cursorScreenX: number,
    cursorScreenY: number,
    anchorRatio: number,
    dragOffsetY: number,
  ) => Promise<boolean>;
  start_window_resize?: (
    edge: NativeWindowResizeEdge,
    cursorScreenX?: number,
    cursorScreenY?: number,
  ) => Promise<boolean>;
  record_startup_mark?: (
    label: string,
    browserElapsedMs?: number | null,
  ) => Promise<boolean> | boolean;
  restore_window_for_drag: (
    cursorScreenX: number,
    cursorScreenY: number,
    anchorRatio: number,
    dragOffsetY: number,
  ) => Promise<WindowBounds>;
  select_project_folder: () => Promise<string | null>;
}

export interface DesktopShellContextValue {
  state: DesktopShellState;
  minimize: () => Promise<void>;
  toggleMaximize: () => Promise<void>;
  close: () => Promise<void>;
  getBounds: () => Promise<WindowBounds>;
  persistWindowSizePreferences: () => Promise<void>;
  setBounds: (bounds: WindowBounds) => Promise<boolean>;
  moveWindow: (x: number, y: number) => Promise<boolean>;
  canStartNativeDrag: boolean;
  canStartNativeResize: boolean;
  nativeResizeMode: NativeWindowResizeMode;
  canHideToTray: boolean;
  startNativeDrag: (
    cursorScreenX: number,
    cursorScreenY: number,
    anchorRatio: number,
    dragOffsetY: number,
  ) => Promise<boolean>;
  startNativeResize: (
    edge: NativeWindowResizeEdge,
    cursorScreenX: number,
    cursorScreenY: number,
  ) => Promise<boolean>;
  restoreForDrag: (
    cursorScreenX: number,
    cursorScreenY: number,
    anchorRatio: number,
    dragOffsetY: number,
  ) => Promise<WindowBounds>;
  selectProjectFolder: () => Promise<string | null>;
}

export const defaultDesktopShellState: DesktopShellState = {
  available: false,
  frameless: false,
  maximized: false,
  minWidth: 1080,
  minHeight: 720,
};

export const defaultDesktopShellCapabilities: DesktopShellCapabilities = {
  nativeWindowDragSupported: false,
  nativeWindowResizeMode: "none",
  nativeWindowResizeSupported: false,
  pageZoomSupported: false,
  platform: "unknown",
  systemTraySupported: false,
};

export const emptyWindowBounds: WindowBounds = {
  x: 0,
  y: 0,
  width: 0,
  height: 0,
};
