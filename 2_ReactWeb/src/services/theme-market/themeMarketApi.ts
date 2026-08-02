import type {
  ThemeMarketFilters,
  ThemeMarketIndex,
  ThemeMarketSettings,
} from "../../features/theme-market/model/themeMarket";
import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";

export const DEFAULT_THEME_MARKET_SOURCE = "https://likemirage.github.io/Tiance-themes";

export type ThemeMarketInstallResponse = {
  categoryId: string;
  projectId: string;
  themeId: string;
  version: string;
};

export function getThemeMarketSettings(signal?: AbortSignal) {
  return fetchJson<ThemeMarketSettings>("/api/themes/market/settings", { signal });
}

export function getThemeMarketIndex(signal?: AbortSignal) {
  return fetchJson<ThemeMarketIndex>("/api/themes/market/index", { signal });
}

export function connectThemeMarket(source: string, signal?: AbortSignal) {
  return fetchJson<ThemeMarketIndex>("/api/themes/market/connect", {
    body: JSON.stringify({ source }),
    method: "POST",
    signal,
  });
}

export function saveThemeMarketFilters(filters: ThemeMarketFilters, signal?: AbortSignal) {
  return fetchJson<ThemeMarketSettings>("/api/themes/market/settings", {
    body: JSON.stringify({ filters }),
    method: "PUT",
    signal,
  });
}

export function installThemeFromMarket(
  themeId: string,
  categoryId: string | null,
  replaceExisting: boolean,
  signal?: AbortSignal,
) {
  return fetchJson<ThemeMarketInstallResponse>(
    `/api/themes/market/themes/${encodeURIComponent(themeId)}/install`,
    {
      body: JSON.stringify({ categoryId, replaceExisting }),
      method: "POST",
      signal,
    },
  );
}

export function getThemeMarketPreviewUrl(previewPath: string, cacheKey: string) {
  const path = previewPath.startsWith("/") ? previewPath : `/${previewPath}`;
  return `${env.apiBaseUrl}${path}?key=${encodeURIComponent(cacheKey)}`;
}
