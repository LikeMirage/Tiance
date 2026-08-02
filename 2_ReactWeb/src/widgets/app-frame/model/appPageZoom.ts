import type { PageZoomSnapshot } from "../../../shared/types/desktopShell";
import {
  getDesktopPageZoomPreference,
  saveDesktopPageZoomPreference,
} from "../../../services/desktop/pageZoomPreferences";

export const APP_PAGE_ZOOM_MIN_FACTOR = 0.6;
export const APP_PAGE_ZOOM_MAX_FACTOR = 1.25;
export const APP_PAGE_ZOOM_STEP = 0.05;
export const APP_PAGE_ZOOM_DEFAULT_FACTOR = 1;

export type AppPageZoomMode = "native" | "unavailable";

export type AppPageZoomSnapshot = {
  applying: boolean;
  mode: AppPageZoomMode;
  zoomFactor: number;
};

const appPageZoomListeners = new Set<() => void>();

let appPageZoomSnapshot: AppPageZoomSnapshot = {
  applying: false,
  mode: "unavailable",
  zoomFactor: APP_PAGE_ZOOM_DEFAULT_FACTOR,
};
let appPageZoomSyncPromise: Promise<void> | null = null;
let appPageZoomMutationSequence = 0;
let appPageZoomManuallyAdjusted = false;

export function subscribeAppPageZoom(listener: () => void) {
  appPageZoomListeners.add(listener);
  return () => {
    appPageZoomListeners.delete(listener);
  };
}

export function getAppPageZoomSnapshot() {
  return appPageZoomSnapshot;
}

export function getStoredAppPageZoomFactor() {
  return appPageZoomSnapshot.zoomFactor;
}

export async function syncAppPageZoomWithRuntime() {
  if (appPageZoomSyncPromise) {
    return appPageZoomSyncPromise;
  }

  appPageZoomSyncPromise = (async () => {
    const syncSequence = appPageZoomMutationSequence;
    const storedZoomFactor = appPageZoomManuallyAdjusted
      ? appPageZoomSnapshot.zoomFactor
      : await loadStoredAppPageZoomFactor();
    if (syncSequence !== appPageZoomMutationSequence) {
      return;
    }
    await applyAppPageZoomFactor(storedZoomFactor ?? APP_PAGE_ZOOM_DEFAULT_FACTOR, {
      persist: false,
      sequence: syncSequence,
    });
  })().finally(() => {
    appPageZoomSyncPromise = null;
  });

  return appPageZoomSyncPromise;
}

export async function setAppPageZoomFactor(
  zoomFactor: number,
) {
  appPageZoomMutationSequence += 1;
  appPageZoomManuallyAdjusted = true;
  return applyAppPageZoomFactor(zoomFactor, {
    persist: true,
    sequence: appPageZoomMutationSequence,
  });
}

function setAppPageZoomSnapshot(nextSnapshot: AppPageZoomSnapshot) {
  if (
    appPageZoomSnapshot.applying === nextSnapshot.applying &&
    appPageZoomSnapshot.mode === nextSnapshot.mode &&
    appPageZoomSnapshot.zoomFactor === nextSnapshot.zoomFactor
  ) {
    return;
  }

  appPageZoomSnapshot = nextSnapshot;
  appPageZoomListeners.forEach((listener) => listener());
}

async function applyAppPageZoomFactor(
  zoomFactor: number,
  options: {
    persist: boolean;
    sequence: number;
  },
) {
  const normalizedZoomFactor = normalizeAppPageZoomFactor(zoomFactor);

  setAppPageZoomSnapshot({
    ...appPageZoomSnapshot,
    applying: true,
    zoomFactor: normalizedZoomFactor,
  });

  const nativeResult = await applyNativePageZoomFactor(normalizedZoomFactor);
  if (nativeResult?.available) {
    if (options.sequence !== appPageZoomMutationSequence) {
      return;
    }

    clearBrowserZoomFallback();
    const appliedZoomFactor = normalizeAppPageZoomFactor(nativeResult.zoomFactor);
    if (options.persist) {
      void saveStoredAppPageZoomFactor(appliedZoomFactor);
    }
    setAppPageZoomSnapshot({
      applying: false,
      mode: "native",
      zoomFactor: appliedZoomFactor,
    });
    return;
  }

  if (options.sequence !== appPageZoomMutationSequence) {
    return;
  }

  clearBrowserZoomFallback();
  if (options.persist) {
    void saveStoredAppPageZoomFactor(normalizedZoomFactor);
  }
  setAppPageZoomSnapshot({
    applying: false,
    mode: "unavailable",
    zoomFactor: normalizedZoomFactor,
  });
}

async function applyNativePageZoomFactor(
  zoomFactor: number,
): Promise<PageZoomSnapshot | null> {
  const api = window.pywebview?.api;
  if (!api?.set_page_zoom_factor) {
    return null;
  }

  try {
    return await api.set_page_zoom_factor(zoomFactor);
  } catch {
    return null;
  }
}

function clearBrowserZoomFallback() {
  document.body.style.removeProperty("zoom");
}

async function loadStoredAppPageZoomFactor() {
  try {
    const zoomFactor = await getDesktopPageZoomPreference();
    return typeof zoomFactor === "number" ? normalizeAppPageZoomFactor(zoomFactor) : null;
  } catch {
    return null;
  }
}

async function saveStoredAppPageZoomFactor(zoomFactor: number) {
  try {
    await saveDesktopPageZoomPreference(zoomFactor);
  } catch {
    // 本机偏好保存失败不阻断缩放本身。
  }
}

function normalizeAppPageZoomFactor(value: unknown) {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) {
    return APP_PAGE_ZOOM_DEFAULT_FACTOR;
  }

  const clamped = Math.max(
    APP_PAGE_ZOOM_MIN_FACTOR,
    Math.min(APP_PAGE_ZOOM_MAX_FACTOR, number),
  );
  return Math.round(clamped * 100) / 100;
}
