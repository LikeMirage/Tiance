import { fetchJson } from "../http/httpClient";

export type ProjectContentFile = {
  name: string;
  path: string;
  mtime_ms: number;
};

export type ProjectContentFileSnapshot = {
  project_id: string;
  items: ProjectContentFile[];
  unreadable_paths: string[];
};

export function getProjectContentFiles(
  projectId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ProjectContentFileSnapshot>(
    `/api/projects/${encodeURIComponent(projectId)}/files/snapshot`,
    { signal: init?.signal },
  );
}

export function refreshProjectContentFiles(
  projectId: string, paths: string[], init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ProjectContentFileSnapshot>(
    `/api/projects/${encodeURIComponent(projectId)}/files/snapshot`,
    { method: "POST", body: JSON.stringify({ paths }), signal: init?.signal },
  );
}
