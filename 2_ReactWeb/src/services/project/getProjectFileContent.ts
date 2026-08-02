import { fetchJson } from "../http/httpClient";

export type ProjectFileContentResponse = {
  project_id: string;
  path: string;
  content: string;
  mtime_ms: number;
};

export function getProjectFileContent(projectId: string, path: string) {
  return fetchJson<ProjectFileContentResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files/content?path=${encodeURIComponent(path)}`,
  );
}
