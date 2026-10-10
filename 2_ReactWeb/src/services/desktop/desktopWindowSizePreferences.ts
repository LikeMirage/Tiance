import type {
  DesktopWindowSizePreferences,
  DesktopWindowSizePreferenceUpdate,
} from "../../entities/desktop-shell/model/desktopWindowSizePreferences";
import {
  normalizeDesktopWindowSizePreferences,
  normalizeDesktopWindowSizePreferenceUpdate,
} from "../../entities/desktop-shell/model/desktopWindowSizePreferences";
import { fetchJson } from "../http/httpClient";

// Best-effort window preferences only, never document or conversation saves.
// Includes native bounds lookup on exit; expiry aborts HTTP and keeps the last
// persisted size rather than preventing close/hide indefinitely.
export const DESKTOP_WINDOW_SIZE_REQUEST_TIMEOUT_MS = 2500;

type DesktopWindowSizePreferencesResponse = {
  height: number;
  maximized: boolean;
  version: number;
  width: number;
};

type DesktopWindowSizePreferencesSaveRequest = {
  height?: number;
  maximized?: boolean;
  width?: number;
};

export async function getDesktopWindowSizePreferences(
  init?: RequestInit,
): Promise<DesktopWindowSizePreferences> {
  const response = await fetchJson<DesktopWindowSizePreferencesResponse>(
    "/api/desktop/window-size-preferences",
    init,
  );
  return normalizeDesktopWindowSizePreferences(response);
}

export function getDesktopWindowSizePreferencesWithTimeout() {
  return withinDesktopWindowSizeDeadline((signal) => getDesktopWindowSizePreferences({ signal }));
}

export async function withinDesktopWindowSizeDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      controller.abort();
      reject(new DOMException("Window preference save/read timed out", "TimeoutError"));
    }, DESKTOP_WINDOW_SIZE_REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([operation(controller.signal), timeout]);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function saveDesktopWindowSizePreferences(
  update: DesktopWindowSizePreferenceUpdate,
  signal?: AbortSignal,
): Promise<DesktopWindowSizePreferences> {
  const normalized = normalizeDesktopWindowSizePreferenceUpdate(update);
  const response = await fetchJson<DesktopWindowSizePreferencesResponse>(
    "/api/desktop/window-size-preferences",
    {
      method: "PUT",
      signal,
      body: JSON.stringify(mapDesktopWindowSizePreferenceUpdate(normalized)),
    },
  );
  return normalizeDesktopWindowSizePreferences(response);
}

function mapDesktopWindowSizePreferenceUpdate(
  update: DesktopWindowSizePreferenceUpdate,
): DesktopWindowSizePreferencesSaveRequest {
  const payload: DesktopWindowSizePreferencesSaveRequest = {};
  if (update.height !== undefined) {
    payload.height = update.height;
  }
  if (update.maximized !== undefined) {
    payload.maximized = update.maximized;
  }
  if (update.width !== undefined) {
    payload.width = update.width;
  }
  return payload;
}
