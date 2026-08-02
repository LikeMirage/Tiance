import type {
  ProjectMarketFilters,
  ProjectMarketIndex,
  ProjectMarketInstallOperation,
  ProjectMarketScope,
  ProjectMarketSettings,
} from "../../features/project-market/model/projectMarket";
import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";

const DEFAULT_PROJECT_MARKET_SOURCES: Record<ProjectMarketScope, string> = {
  experience: "https://likemirage.github.io/Tiance-experience",
  knowledge: "https://likemirage.github.io/Tiance-knowledge",
  project: "https://likemirage.github.io/Tiance-projects",
};

export function getDefaultProjectMarketSource(scope: ProjectMarketScope) {
  return DEFAULT_PROJECT_MARKET_SOURCES[scope];
}

function projectMarketApiBase(scope: ProjectMarketScope) {
  if (scope === "knowledge") return "/api/knowledge/market";
  if (scope === "experience") return "/api/experience/market";
  return "/api/projects/market";
}

export function getProjectMarketSettings(scope: ProjectMarketScope, signal?: AbortSignal) {
  return fetchJson<ProjectMarketSettings>(`${projectMarketApiBase(scope)}/settings`, { signal });
}

export function getProjectMarketIndex(scope: ProjectMarketScope, signal?: AbortSignal) {
  return fetchJson<ProjectMarketIndex>(`${projectMarketApiBase(scope)}/index`, { signal });
}

export function connectProjectMarket(
  scope: ProjectMarketScope,
  source: string,
  signal?: AbortSignal,
) {
  return fetchJson<ProjectMarketIndex>(`${projectMarketApiBase(scope)}/connect`, {
    body: JSON.stringify({ source }),
    method: "POST",
    signal,
  });
}

export function restoreDefaultProjectMarket(scope: ProjectMarketScope, signal?: AbortSignal) {
  return fetchJson<ProjectMarketIndex>(`${projectMarketApiBase(scope)}/restore-default`, {
    method: "POST",
    signal,
  });
}

export function saveProjectMarketFilters(
  scope: ProjectMarketScope,
  filters: ProjectMarketFilters,
  signal?: AbortSignal,
) {
  return fetchJson<ProjectMarketSettings>(`${projectMarketApiBase(scope)}/settings`, {
    body: JSON.stringify({ filters }),
    method: "PUT",
    signal,
  });
}

export function selectProjectOnlineSource(source: string, signal?: AbortSignal) {
  return fetchJson<ProjectMarketSettings>("/api/projects/market/source", {
    body: JSON.stringify({ source }),
    method: "PUT",
    signal,
  });
}

export function startProjectMarketInstall(
  scope: ProjectMarketScope,
  marketProjectId: string,
  categoryId: string,
  signal?: AbortSignal,
) {
  return fetchJson<ProjectMarketInstallOperation>(
    `${projectMarketApiBase(scope)}/projects/${encodeURIComponent(marketProjectId)}/install`,
    {
      body: JSON.stringify({ categoryId }),
      method: "POST",
      signal,
    },
  );
}

export function getProjectMarketInstallOperation(
  scope: ProjectMarketScope,
  operationId: string,
  signal?: AbortSignal,
) {
  return fetchJson<ProjectMarketInstallOperation>(
    `${projectMarketApiBase(scope)}/operations/${encodeURIComponent(operationId)}`,
    { signal },
  );
}

export function getProjectMarketPreviewUrl(previewPath: string, cacheKey: string) {
  const path = previewPath.startsWith("/") ? previewPath : `/${previewPath}`;
  return `${env.apiBaseUrl}${path}?key=${encodeURIComponent(cacheKey)}`;
}
