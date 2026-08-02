import type { ProjectCategoryListResponse } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function getProjectCategories() {
  return fetchJson<ProjectCategoryListResponse>("/api/projects/categories");
}
