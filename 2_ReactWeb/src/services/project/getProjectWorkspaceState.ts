import { fetchJson } from "../http/httpClient";
import type { WorkspaceTabEntry } from "../../entities/editor/model/editorDocument";

export type WorkspaceStateResponse = {
  project_id: string;
  expanded_paths: string[];
  open_file_paths: string[];
  open_tabs?: WorkspaceTabEntry[] | null;
  active_file_path: string | null;
  active_dashboard:
    | "conversation_overview"
    | "project_memory"
    | "knowledge_content"
    | "role_configuration"
    | "theme_configuration"
    | "basics"
    | "permissions"
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
