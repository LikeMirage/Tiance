import type {
  DesktopShellApi,
  DesktopShellCapabilities,
  DesktopShellState,
  NativeWindowResizeEdge,
  NativeWindowResizeMode,
  WindowBounds,
  WindowStateSnapshot,
} from "../../../shared/types/desktopShell";
import {
  DESKTOP_WINDOW_SIZE_DEFAULTS,
  normalizeDesktopWindowSizePreferences,
} from "../../../entities/desktop-shell/model/desktopWindowSizePreferences";
import { saveDesktopWindowSizePreferences } from "../../../services/desktop/desktopWindowSizePreferences";
import {
  defaultDesktopShellCapabilities,
  defaultDesktopShellState,
  emptyWindowBounds,
} from "../../../shared/types/desktopShell";

const desktopShellListeners = new Set<() => void>();

let desktopShellState: DesktopShellState = defaultDesktopShellState;
let desktopShellCapabilities: DesktopShellCapabilities = defaultDesktopShellCapabilities;
let desktopShellSnapshot = {
  capabilities: desktopShellCapabilities,
  state: desktopShellState,
};
let desktopShellBridgeBound = false;
let desktopShellBridgeSubscribers = 0;
let desktopShellBridgeSession = 0;
let desktopShellSyncPromise: Promise<void> | null = null;
let desktopShellRetryTimer: number | null = null;
let desktopShellRetryAttempts = 0;
let lastNormalWindowSize = {
  height: DESKTOP_WINDOW_SIZE_DEFAULTS.height,
  width: DESKTOP_WINDOW_SIZE_DEFAULTS.width,
};

const DESKTOP_SHELL_RETRY_INTERVAL_MS = 250;
const DESKTOP_SHELL_RETRY_LIMIT = 40;

export function subscribeDesktopShell(listener: () => void) {
  desktopShellListeners.add(listener);
  return () => {
    desktopShellListeners.delete(listener);
  };
}

export function getDesktopShellSnapshot() {
  return desktopShellSnapshot;
}

export function acquireDesktopShellBridge() {
  desktopShellBridgeSubscribers += 1;

  if (!desktopShellBridgeBound) {
    desktopShellBridgeBound = true;
    desktopShellBridgeSession += 1;
    window.addEventListener("pywebviewready", handleDesktopShellReady);
    document.addEventListener("pywebviewready", handleDesktopShellReady as EventListener);
    window.addEventListener("focus", handleDesktopShellReady);
    document.addEventListener("visibilitychange", handleVisibilityChange);
  }

  startDesktopShellRetryLoop();
  void syncDesktopShellState();

  return () => {
    releaseDesktopShellBridge();
  };
}

export async function revealDesktopShellWindow() {
  const api = getDesktopShellApi();
  if (!api?.reveal_window) {
    return false;
  }

  return api.reveal_window();
}

export async function minimizeDesktopShell() {
  const api = getDesktopShellApi();
  if (!api) {
    return;
  }

  await api.minimize_window();
}

export async function hideDesktopShellToTray() {
  const api = getDesktopShellApi();
  if (!api?.hide_window_to_tray) {
    return false;
  }

  await persistDesktopShellWindowSizePreferences();
  return api.hide_window_to_tray();
}

export async function toggleMaximizeDesktopShell() {
  const api = getDesktopShellApi();
  if (!api) {
    return;
  }

  const wasMaximized = desktopShellState.maximized;
  if (!wasMaximized) {
    const bounds = await api.get_window_bounds();
    rememberNormalWindowSize(bounds);
  }

  const nextState = await api.toggle_maximize_window();
  applyWindowState(nextState);
  if (nextState.maximized) {
    await persistKnownDesktopWindowSizePreferences(true);
    return;
  }

  const bounds = await api.get_window_bounds();
  rememberNormalWindowSize(bounds);
  await persistKnownDesktopWindowSizePreferences(false);
}

export async function closeDesktopShell() {
  const api = getDesktopShellApi();
  if (!api) {
    return;
  }

  await persistDesktopShellWindowSizePreferences();
  await api.close_window();
}

export async function getDesktopShellBounds() {
  const api = getDesktopShellApi();
  if (!api) {
    return emptyWindowBounds;
  }

  return api.get_window_bounds();
}

export async function setDesktopShellBounds(bounds: WindowBounds) {
  const api = getDesktopShellApi();
  if (!api) {
    return false;
  }

  const didSetBounds = await api.set_window_bounds(bounds.x, bounds.y, bounds.width, bounds.height);
  if (didSetBounds) {
    rememberNormalWindowSize(bounds);
  }
  return didSetBounds;
}

export async function moveDesktopShellWindow(x: number, y: number) {
  const api = getDesktopShellApi();
  if (!api) {
    return false;
  }

  return api.move_window(x, y);
}

export function canStartDesktopShellNativeDrag() {
  return (
    desktopShellCapabilities.nativeWindowDragSupported &&
    typeof getDesktopShellApi()?.start_window_drag === "function"
  );
}

export function canStartDesktopShellNativeResize() {
  return (
    desktopShellCapabilities.nativeWindowResizeMode === "api" &&
    desktopShellCapabilities.nativeWindowResizeSupported &&
    typeof getDesktopShellApi()?.start_window_resize === "function"
  );
}

export async function startDesktopShellNativeDrag(
  cursorScreenX: number,
  cursorScreenY: number,
  anchorRatio: number,
  dragOffsetY: number,
) {
  const api = getDesktopShellApi();
  if (!api?.start_window_drag) {
    return false;
  }

  return api.start_window_drag(cursorScreenX, cursorScreenY, anchorRatio, dragOffsetY);
}

export async function startDesktopShellNativeResize(
  edge: NativeWindowResizeEdge,
  cursorScreenX: number,
  cursorScreenY: number,
) {
  const api = getDesktopShellApi();
  if (!api?.start_window_resize) {
    return false;
  }

  return api.start_window_resize(edge, cursorScreenX, cursorScreenY);
}

export async function selectDesktopShellProjectFolder(): Promise<string | null> {
  const api = getDesktopShellApi();
  if (!api) {
    return null;
  }

  return api.select_project_folder();
}

export async function restoreDesktopShellForDrag(
  cursorScreenX: number,
  cursorScreenY: number,
  anchorRatio: number,
  dragOffsetY: number,
) {
  const api = getDesktopShellApi();
  if (!api) {
    return emptyWindowBounds;
  }

  const bounds = await api.restore_window_for_drag(
    cursorScreenX,
    cursorScreenY,
    anchorRatio,
    dragOffsetY,
  );

  setDesktopShellState({
    ...desktopShellState,
    available: true,
    maximized: false,
  });
  rememberNormalWindowSize(bounds);
  void persistKnownDesktopWindowSizePreferences(false);

  return bounds;
}

export async function persistDesktopShellWindowSizePreferences() {
  const api = getDesktopShellApi();
  if (!api) {
    return;
  }

  try {
    const state = await api.get_window_state();
    applyWindowState(state);
    if (state.maximized) {
      await persistKnownDesktopWindowSizePreferences(true);
      return;
    }

    const bounds = await api.get_window_bounds();
    rememberNormalWindowSize(bounds);
    await persistKnownDesktopWindowSizePreferences(false);
  } catch (error) {
    console.warn("Failed to persist desktop window size preferences.", error);
  }
}

function getDesktopShellApi(): DesktopShellApi | null {
  return window.pywebview?.api ?? null;
}

function releaseDesktopShellBridge() {
  desktopShellBridgeSubscribers = Math.max(0, desktopShellBridgeSubscribers - 1);

  if (!desktopShellBridgeBound || desktopShellBridgeSubscribers > 0) {
    return;
  }

  desktopShellBridgeBound = false;
  desktopShellBridgeSession += 1;
  window.removeEventListener("pywebviewready", handleDesktopShellReady);
  document.removeEventListener("pywebviewready", handleDesktopShellReady as EventListener);
  window.removeEventListener("focus", handleDesktopShellReady);
  document.removeEventListener("visibilitychange", handleVisibilityChange);
  stopDesktopShellRetryLoop();
  desktopShellSyncPromise = null;
  setDesktopShellState(defaultDesktopShellState);
}

function handleDesktopShellReady() {
  startDesktopShellRetryLoop();
  void syncDesktopShellState();
}

function handleVisibilityChange() {
  if (document.visibilityState !== "visible") {
    return;
  }

  handleDesktopShellReady();
}

function startDesktopShellRetryLoop() {
  if (
    desktopShellRetryTimer !== null ||
    desktopShellState.available ||
    !desktopShellBridgeBound ||
    desktopShellBridgeSubscribers === 0
  ) {
    return;
  }

  desktopShellRetryAttempts = 0;
  desktopShellRetryTimer = window.setInterval(() => {
    if (desktopShellState.available) {
      stopDesktopShellRetryLoop();
      return;
    }

    desktopShellRetryAttempts += 1;
    void syncDesktopShellState();

    if (desktopShellRetryAttempts >= DESKTOP_SHELL_RETRY_LIMIT) {
      stopDesktopShellRetryLoop();
    }
  }, DESKTOP_SHELL_RETRY_INTERVAL_MS);
}

function stopDesktopShellRetryLoop() {
  if (desktopShellRetryTimer === null) {
    return;
  }

  window.clearInterval(desktopShellRetryTimer);
  desktopShellRetryTimer = null;
  desktopShellRetryAttempts = 0;
}

function setDesktopShellState(nextState: DesktopShellState) {
  if (
    desktopShellState.available === nextState.available &&
    desktopShellState.frameless === nextState.frameless &&
    desktopShellState.maximized === nextState.maximized &&
    desktopShellState.minWidth === nextState.minWidth &&
    desktopShellState.minHeight === nextState.minHeight
  ) {
    return;
  }

  desktopShellState = nextState;
  desktopShellSnapshot = {
    capabilities: desktopShellCapabilities,
    state: desktopShellState,
  };
  desktopShellListeners.forEach((listener) => listener());
}

function applyWindowState(nextState: WindowStateSnapshot) {
  stopDesktopShellRetryLoop();
  setDesktopShellState({
    available: true,
    frameless: nextState.frameless,
    maximized: nextState.maximized,
    minWidth: nextState.minWidth,
    minHeight: nextState.minHeight,
  });
}

function applyDesktopShellUnavailable() {
  setDesktopShellState(defaultDesktopShellState);
  setDesktopShellCapabilities(defaultDesktopShellCapabilities);
  startDesktopShellRetryLoop();
}

function setDesktopShellCapabilities(nextCapabilities: DesktopShellCapabilities) {
  if (
    desktopShellCapabilities.nativeWindowDragSupported ===
      nextCapabilities.nativeWindowDragSupported &&
    desktopShellCapabilities.nativeWindowResizeMode === nextCapabilities.nativeWindowResizeMode &&
    desktopShellCapabilities.nativeWindowResizeSupported ===
      nextCapabilities.nativeWindowResizeSupported &&
    desktopShellCapabilities.pageZoomSupported === nextCapabilities.pageZoomSupported &&
    desktopShellCapabilities.platform === nextCapabilities.platform &&
    desktopShellCapabilities.systemTraySupported === nextCapabilities.systemTraySupported
  ) {
    return;
  }

  desktopShellCapabilities = nextCapabilities;
  desktopShellSnapshot = {
    capabilities: desktopShellCapabilities,
    state: desktopShellState,
  };
  desktopShellListeners.forEach((listener) => listener());
}

function normalizeDesktopShellCapabilities(
  capabilities: DesktopShellCapabilities | undefined,
): DesktopShellCapabilities {
  if (!capabilities) {
    return defaultDesktopShellCapabilities;
  }

  const nativeWindowResizeMode = normalizeNativeWindowResizeMode(
    capabilities.nativeWindowResizeMode,
    capabilities.nativeWindowResizeSupported,
  );

  return {
    nativeWindowDragSupported: capabilities.nativeWindowDragSupported === true,
    nativeWindowResizeMode,
    nativeWindowResizeSupported:
      nativeWindowResizeMode !== "none" || capabilities.nativeWindowResizeSupported === true,
    pageZoomSupported: capabilities.pageZoomSupported === true,
    platform:
      typeof capabilities.platform === "string" && capabilities.platform.trim()
        ? capabilities.platform
        : defaultDesktopShellCapabilities.platform,
    systemTraySupported: capabilities.systemTraySupported === true,
  };
}

function normalizeNativeWindowResizeMode(
  value: unknown,
  supported: unknown,
): NativeWindowResizeMode {
  if (value === "api" || value === "system-edge") {
    return value;
  }

  return supported === true ? "api" : "none";
}

function rememberNormalWindowSize(size: { width: number; height: number }) {
  const preferences = normalizeDesktopWindowSizePreferences({
    height: size.height,
    maximized: false,
    width: size.width,
  });
  lastNormalWindowSize = {
    height: preferences.height,
    width: preferences.width,
  };
}

async function persistKnownDesktopWindowSizePreferences(maximized: boolean) {
  try {
    await saveDesktopWindowSizePreferences({
      height: lastNormalWindowSize.height,
      maximized,
      width: lastNormalWindowSize.width,
    });
  } catch (error) {
    console.warn("Failed to save desktop window size preferences.", error);
  }
}

async function syncDesktopShellState() {
  if (desktopShellSyncPromise) {
    return desktopShellSyncPromise;
  }

  const session = desktopShellBridgeSession;
  desktopShellSyncPromise = (async () => {
    const api = getDesktopShellApi();

    if (!api) {
      applyDesktopShellUnavailable();
      return;
    }

    try {
      const nextState = await api.get_window_state();
      const nextCapabilities = await loadDesktopShellCapabilities(api);

      if (!desktopShellBridgeBound || session !== desktopShellBridgeSession) {
        return;
      }

      applyWindowState(nextState);
      setDesktopShellCapabilities(normalizeDesktopShellCapabilities(nextCapabilities));
    } catch {
      if (!desktopShellBridgeBound || session !== desktopShellBridgeSession) {
        return;
      }

      applyDesktopShellUnavailable();
    }
  })().finally(() => {
    desktopShellSyncPromise = null;
  });

  return desktopShellSyncPromise;
}

async function loadDesktopShellCapabilities(
  api: DesktopShellApi,
): Promise<DesktopShellCapabilities> {
  if (!api.get_shell_capabilities) {
    return defaultDesktopShellCapabilities;
  }

  try {
    return normalizeDesktopShellCapabilities(await api.get_shell_capabilities());
  } catch {
    return defaultDesktopShellCapabilities;
  }
}
