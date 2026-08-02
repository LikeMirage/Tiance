import type { ThemeDefinition, ThemeListResponse } from "../../shared/theme";
import { fetchJson } from "../http/httpClient";

const ACTIVE_THEME_REQUEST_TIMEOUT_MS = 2500;

export function getActiveTheme(init?: RequestInit): Promise<ThemeDefinition> {
  return fetchJson<ThemeDefinition>("/api/themes/active", init);
}

export function listThemes(init?: RequestInit): Promise<ThemeListResponse> {
  return fetchJson<ThemeListResponse>("/api/themes", init);
}

export function getActiveThemeWithTimeout(): Promise<ThemeDefinition> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort();
  }, ACTIVE_THEME_REQUEST_TIMEOUT_MS);

  return getActiveTheme({ signal: controller.signal }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

export function getTheme(themeId: string): Promise<ThemeDefinition> {
  return fetchJson<ThemeDefinition>(`/api/themes/${themeId}`);
}

export function setActiveTheme(themeId: string): Promise<ThemeDefinition> {
  return fetchJson<ThemeDefinition>("/api/themes/active", {
    method: "PUT",
    body: JSON.stringify({ themeId }),
  });
}

export function updateTheme(
  themeId: string,
  payload: ThemeDefinition,
): Promise<ThemeDefinition> {
  return fetchJson<ThemeDefinition>(`/api/themes/${themeId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
