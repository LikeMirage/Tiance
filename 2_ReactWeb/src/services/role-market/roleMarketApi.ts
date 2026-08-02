import type {
  RoleMarketFilters,
  RoleMarketIndex,
  RoleMarketSettings,
} from "../../features/role-market/model/roleMarket";
import { fetchJson } from "../http/httpClient";

export const DEFAULT_ROLE_MARKET_SOURCE = "https://likemirage.github.io/Tiance-roles";

export type RoleMarketInstallResponse = {
  categoryId: string;
  projectId: string;
  roleId: string;
  updated: boolean;
  version: string;
};

export function getRoleMarketSettings(signal?: AbortSignal) {
  return fetchJson<RoleMarketSettings>("/api/roles/market/settings", { signal });
}

export function getRoleMarketIndex(signal?: AbortSignal) {
  return fetchJson<RoleMarketIndex>("/api/roles/market/index", { signal });
}

export function connectRoleMarket(source: string, signal?: AbortSignal) {
  return fetchJson<RoleMarketIndex>("/api/roles/market/connect", {
    body: JSON.stringify({ source }),
    method: "POST",
    signal,
  });
}

export function saveRoleMarketFilters(filters: RoleMarketFilters, signal?: AbortSignal) {
  return fetchJson<RoleMarketSettings>("/api/roles/market/settings", {
    body: JSON.stringify({ filters }),
    method: "PUT",
    signal,
  });
}

export function installRoleFromMarket(
  roleId: string,
  categoryId: string | null,
  replaceExisting: boolean,
  signal?: AbortSignal,
) {
  return fetchJson<RoleMarketInstallResponse>(
    `/api/roles/market/roles/${encodeURIComponent(roleId)}/install`,
    {
      body: JSON.stringify({ categoryId, replaceExisting }),
      method: "POST",
      signal,
    },
  );
}
