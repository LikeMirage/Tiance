import { fetchJson } from "../http/httpClient";
import type { WorkspaceStateResponse } from "./getProjectWorkspaceState";

export type ProjectWorkspaceTabsAction =
  | "list_tabs"
  | "open_file"
  | "focus_file"
  | "close_clean_tabs"
  | "close_others_clean";

export type ProjectWorkspaceTabsActionResponse = WorkspaceStateResponse & {
  action: ProjectWorkspaceTabsAction;
  closed_file_paths: string[];
  missing_file_paths: string[];
};

export function applyProjectWorkspaceTabsAction(
  projectId: string,
  payload: {
    action: ProjectWorkspaceTabsAction;
    path?: string;
    paths?: string[];
  },
) {
  return fetchJson<ProjectWorkspaceTabsActionResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/workspace-state/editor-tabs`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
