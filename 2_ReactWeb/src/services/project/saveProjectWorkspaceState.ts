import { fetchJson } from "../http/httpClient";
import type { WorkspaceStateResponse } from "./getProjectWorkspaceState";

export function saveProjectWorkspaceState(
  projectId: string,
  payload: {
    expanded_paths: string[];
    open_file_paths: string[];
    active_file_path: string | null;
    active_dashboard: WorkspaceStateResponse["active_dashboard"];
  },
) {
  return fetchJson<WorkspaceStateResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/workspace-state`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function patchProjectWorkspaceState(
  projectId: string,
  payload: Partial<{
    expanded_paths: string[];
    open_file_paths: string[];
    active_file_path: string | null;
    active_dashboard: WorkspaceStateResponse["active_dashboard"];
  }>,
) {
  return fetchJson<WorkspaceStateResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/workspace-state`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}
