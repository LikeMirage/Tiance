import type { ProjectOverviewItem } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function getProjectOverview(
  projectId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ProjectOverviewItem>(
    `/api/projects/${encodeURIComponent(projectId)}/overview`,
    { signal: init?.signal },
  );
}
