import type { Project } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function moveProjectToCategory(projectId: string, categoryId: string) {
  return fetchJson<Project>(`/api/projects/${encodeURIComponent(projectId)}/category`, {
    method: "PATCH",
    body: JSON.stringify({ category_id: categoryId }),
  });
}
