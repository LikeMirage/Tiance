import type {
  ToolDependencyInstallRequest,
  ToolDependencyInstallResponse,
  ToolDependencyInstallTaskResponse,
  ToolDependencyListResponse,
  ToolDependencyUninstallRequest,
  ToolDependencyUninstallResponse,
} from "../../entities/tool/model/toolDependency";
import { fetchJson } from "../http/httpClient";

export function getToolFolderDependencies(
  toolsetId: string,
  folderId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ToolDependencyListResponse>(
    toolDependenciesPath(toolsetId, folderId),
    {
      signal: init?.signal,
    },
  );
}

export function installToolFolderDependencies(
  toolsetId: string,
  folderId: string,
  payload: ToolDependencyInstallRequest,
) {
  return fetchJson<ToolDependencyInstallResponse>(
    `${toolDependenciesPath(toolsetId, folderId)}/install`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function startToolFolderDependencyInstallTask(
  toolsetId: string,
  folderId: string,
  payload: ToolDependencyInstallRequest,
) {
  return fetchJson<ToolDependencyInstallTaskResponse>(
    `${toolDependenciesPath(toolsetId, folderId)}/install-tasks`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getToolDependencyInstallTask(taskId: string) {
  return fetchJson<ToolDependencyInstallTaskResponse>(
    `/api/tools/categories/dependency-install-tasks/${encodeURIComponent(taskId)}`,
  );
}

export function uninstallToolFolderDependency(
  toolsetId: string,
  folderId: string,
  payload: ToolDependencyUninstallRequest,
) {
  return fetchJson<ToolDependencyUninstallResponse>(
    `${toolDependenciesPath(toolsetId, folderId)}/uninstall`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

function toolDependenciesPath(toolsetId: string, folderId: string) {
  return `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/dependencies`;
}
