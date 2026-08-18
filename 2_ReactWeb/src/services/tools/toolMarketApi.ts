import type {
  ToolMarketFilters,
  ToolMarketIndex,
  ToolMarketSettings,
} from "../../features/tool-market/model/toolMarket";
import { fetchJson } from "../http/httpClient";

export const DEFAULT_TOOL_MARKET_SOURCE = "https://likemirage.github.io/Tiance-tools";

export type ToolMarketInstallResponse = {
  callName: string;
  categoryId: string;
  projectId: string;
  toolId: string;
  updated: boolean;
  version: string;
  hasDependencies: boolean;
};

export function getToolMarketSettings(signal?: AbortSignal) {
  return fetchJson<ToolMarketSettings>("/api/tools/market/settings", { signal });
}

export function getToolMarketIndex(signal?: AbortSignal) {
  return fetchJson<ToolMarketIndex>("/api/tools/market/index", { signal });
}

export function connectToolMarket(source: string, signal?: AbortSignal) {
  return fetchJson<ToolMarketIndex>("/api/tools/market/connect", {
    body: JSON.stringify({ source }), method: "POST", signal,
  });
}

export function saveToolMarketFilters(filters: ToolMarketFilters, signal?: AbortSignal) {
  return fetchJson<ToolMarketSettings>("/api/tools/market/settings", {
    body: JSON.stringify({ filters }), method: "PUT", signal,
  });
}

export function installToolFromMarket(
  toolId: string,
  categoryId: string | null,
  callName: string | null,
  signal?: AbortSignal,
) {
  return fetchJson<ToolMarketInstallResponse>(
    `/api/tools/market/tools/${encodeURIComponent(toolId)}/install`,
    {
      body: JSON.stringify({ categoryId, callName }), method: "POST", signal,
    },
  );
}
