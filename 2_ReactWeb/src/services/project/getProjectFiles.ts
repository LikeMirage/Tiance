import type { ProjectFileTreeResponse } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function getProjectFiles(
  projectId: string,
  options: { parentPath?: string | null; query?: string } = {},
  init?: Pick<RequestInit, "signal">,
) {
  const search = new URLSearchParams();
  if (options.query?.trim()) search.set("query", options.query.trim());
  if (options.parentPath?.trim()) search.set("parent_path", options.parentPath.trim());
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return fetchJson<ProjectFileTreeResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files${suffix}`,
    {
      signal: init?.signal,
    },
  );
}
