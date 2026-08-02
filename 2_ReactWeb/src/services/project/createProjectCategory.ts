import type {
  ProjectCategory,
  ProjectKind,
} from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function createProjectCategory(
  name?: string | null,
  categoryKind: ProjectKind = "project",
) {
  return fetchJson<ProjectCategory>("/api/projects/categories", {
    method: "POST",
    body: JSON.stringify({
      category_kind: categoryKind,
      name: name ?? null,
    }),
  });
}
