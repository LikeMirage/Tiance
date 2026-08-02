import type { ProjectCategory } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function renameProjectCategory(categoryId: string, name: string) {
  return fetchJson<ProjectCategory>(
    `/api/projects/categories/${encodeURIComponent(categoryId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ name }),
    },
  );
}
