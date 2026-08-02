import type {
  DesktopWindowSizePreferences,
  DesktopWindowSizePreferenceUpdate,
} from "../../entities/desktop-shell/model/desktopWindowSizePreferences";
import {
  normalizeDesktopWindowSizePreferences,
  normalizeDesktopWindowSizePreferenceUpdate,
} from "../../entities/desktop-shell/model/desktopWindowSizePreferences";
import { fetchJson } from "../http/httpClient";

const DESKTOP_WINDOW_SIZE_REQUEST_TIMEOUT_MS = 2500;

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
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort();
  }, DESKTOP_WINDOW_SIZE_REQUEST_TIMEOUT_MS);

  return getDesktopWindowSizePreferences({ signal: controller.signal }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

export async function saveDesktopWindowSizePreferences(
  update: DesktopWindowSizePreferenceUpdate,
): Promise<DesktopWindowSizePreferences> {
  const normalized = normalizeDesktopWindowSizePreferenceUpdate(update);
  const response = await fetchJson<DesktopWindowSizePreferencesResponse>(
    "/api/desktop/window-size-preferences",
    {
      method: "PUT",
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
