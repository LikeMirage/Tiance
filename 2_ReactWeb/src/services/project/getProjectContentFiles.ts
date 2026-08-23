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
