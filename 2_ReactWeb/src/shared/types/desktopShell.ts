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

export interface SystemMetricsSnapshot {
  app?: {
    cpuPercent: number | null;
    memoryBytes: number;
    processCount: number;
  };
  available: boolean;
  reason?: string;
  sampledAt: string;
  system?: {
    cpuPercent: number | null;
    memoryAvailableBytes: number;
    memoryPercent: number;
    memoryTotalBytes: number;
    memoryUsedBytes: number;
  };
}

export interface EditorWebState {
  url: string;
  title: string;
  favicon?: string;
  back: boolean;
  forward: boolean;
  loading: boolean;
  error: string;
}

export interface EditorWebVisit {
  url: string;
  title: string;
  visitedAt: number;
}

export interface EditorWebDownload {
  name: string;
  path: string;
  completedAt: number;
}

export type EditorWebRecordKind = "history" | "downloads";
export type EditorWebPalette = {
  background: string;
  text: string;
  accent: string;
  scrollbarSize: string;
  scrollbarTrack: string;
  scrollbarThumb: string;
  scrollbarThumbHover: string;
};
export type EditorWebAppearanceMode = "original" | "light" | "dark";
export interface EditorWebRecordsPage {
  items: { title: string; target: string; time: number }[];
  nextCursor: string | null;
  recentOnly?: boolean;
}

export interface DesktopShellApi {
  editor_web_appearance?: (mode: EditorWebAppearanceMode, colors: EditorWebPalette) => Promise<void>;
  editor_web_layout?: (id: string, url: string, edges: number[] | null, workspaceRoot?: string) => Promise<void>;
  editor_web_history?: () => Promise<EditorWebVisit[]>;
  editor_web_downloads?: () => Promise<EditorWebDownload[]>;
  editor_web_records_page?: (kind: EditorWebRecordKind, query: string, cursor: string | null) => Promise<EditorWebRecordsPage>;
  editor_web_search_downloads?: (query: string, cursor: string | null) => Promise<EditorWebRecordsPage>;
  editor_web_command?: (id: string, action: string, url: string) => Promise<EditorWebState | null>;
  editor_web_close?: (id: string) => Promise<void>;
  editor_web_cover?: (id: string, requestId: string, waitForPaint?: boolean) => Promise<void>;
  editor_web_present_cover?: (id: string, requestId: string) => Promise<void>;
  respond_microphone_permission?: (requestId: string, allow: boolean) => Promise<boolean>;
  prepare_file_explorer?: () => Promise<boolean> | boolean;
  reveal_window?: () => Promise<boolean> | boolean;
  minimize_window: () => Promise<void>;
  hide_window_to_tray?: () => Promise<boolean> | boolean;
  toggle_maximize_window: () => Promise<WindowStateSnapshot>;
  request_window_close: (intent: "close" | "exit") => Promise<string | null>;
  report_window_close: (requestId: string, state: "waiting" | "saving" | "cancelled") => Promise<boolean>;
  close_window: (requestId: string) => Promise<boolean>;
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
  start_file_drag?: (paths: string[]) => Promise<boolean>;
  copy_external_entries_to_directory?: (
    sourcePaths: string[],
    destinationRoot: string,
  ) => Promise<DesktopExternalFileImportResult>;
  open_external_url?: (url: string) => Promise<boolean>;
  get_page_zoom_factor?: () => Promise<PageZoomSnapshot>;
  get_system_metrics?: () => Promise<SystemMetricsSnapshot>;
  record_renderer_diagnostics?: (metrics: Record<string, number>) => Promise<boolean>;
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
