import { fetchJson } from "../http/httpClient";

export type WorkspaceStateResponse = {
  project_id: string;
  expanded_paths: string[];
  open_file_paths: string[];
  active_file_path: string | null;
  active_dashboard:
    | "conversation_overview"
    | "role_configuration"
    | "theme_configuration"
    | "basics"
    | "examples"
    | "dependencies"
    | "callRecords"
    | null;
};

export function getProjectWorkspaceState(projectId: string) {
  return fetchJson<WorkspaceStateResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/workspace-state`,
  );
}
