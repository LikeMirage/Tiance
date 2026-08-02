import type { Project } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function renameProject(projectId: string, name: string) {
  return fetchJson<Project>(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}
