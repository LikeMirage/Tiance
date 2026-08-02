import type { LocaleDirection } from "../../shared/i18n";
import { fetchJson } from "../http/httpClient";

export type LocaleSelectionMode = "system" | "manual";

export type LocaleSummary = {
  locale: string;
  displayName: string;
  direction: LocaleDirection;
};

export type LocaleList = {
  activeLocale: string;
  locales: LocaleSummary[];
};

export type LocaleSettings = {
  schemaVersion: 1;
  mode: LocaleSelectionMode;
  activeLocale: string;
};

export function listLocales(
  preferredLocale: string,
  signal?: AbortSignal,
): Promise<LocaleList> {
  const query = new URLSearchParams({ preferredLocale });
  return fetchJson<LocaleList>(`/api/locales?${query.toString()}`, { signal });
}

export function getLocaleSettings(signal?: AbortSignal): Promise<LocaleSettings> {
  return fetchJson<LocaleSettings>("/api/locales/settings", { signal });
}

export function updateLocaleSettings(
  mode: LocaleSelectionMode,
  activeLocale: string,
): Promise<LocaleSettings> {
  return fetchJson<LocaleSettings>("/api/locales/settings", {
    method: "PUT",
    body: JSON.stringify({ mode, activeLocale }),
  });
}
