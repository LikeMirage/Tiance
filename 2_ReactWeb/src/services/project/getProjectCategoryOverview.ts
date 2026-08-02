import type { ProjectCategoryOverviewResponse } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function getProjectCategoryOverview(
  categoryId: string,
  init?: Pick<RequestInit, "signal">,
) {
  return fetchJson<ProjectCategoryOverviewResponse>(
    `/api/projects/categories/${encodeURIComponent(categoryId)}/overview`,
    { signal: init?.signal },
  );
}
