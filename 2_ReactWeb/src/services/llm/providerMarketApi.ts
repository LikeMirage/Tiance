import type {
  ProviderMarketFilters,
  ProviderMarketIndex,
  ProviderMarketSettings,
} from "../../features/provider-market/model/providerMarket";
import { fetchJson } from "../http/httpClient";

export const DEFAULT_PROVIDER_MARKET_SOURCE =
  "https://likemirage.github.io/Tiance-providers";

export type ProviderMarketInstallResponse = {
  categoryId: string;
  projectId: string;
  providerId: string;
  updated: boolean;
  version: string;
};

export function getProviderMarketSettings(signal?: AbortSignal) {
  return fetchJson<ProviderMarketSettings>("/api/llm/provider-market/settings", { signal });
}

export function getProviderMarketIndex(signal?: AbortSignal) {
  return fetchJson<ProviderMarketIndex>("/api/llm/provider-market/index", { signal });
}

export function connectProviderMarket(source: string, signal?: AbortSignal) {
  return fetchJson<ProviderMarketIndex>("/api/llm/provider-market/connect", {
    body: JSON.stringify({ source }),
    method: "POST",
    signal,
  });
}

export function saveProviderMarketFilters(
  filters: ProviderMarketFilters,
  signal?: AbortSignal,
) {
  return fetchJson<ProviderMarketSettings>("/api/llm/provider-market/settings", {
    body: JSON.stringify({ filters }),
    method: "PUT",
    signal,
  });
}

export function installProviderFromMarket(
  providerId: string,
  categoryId: string | null,
  replaceExisting: boolean,
  signal?: AbortSignal,
) {
  return fetchJson<ProviderMarketInstallResponse>(
    `/api/llm/provider-market/providers/${encodeURIComponent(providerId)}/install`,
    {
      body: JSON.stringify({ categoryId, replaceExisting }),
      method: "POST",
      signal,
    },
  );
}
