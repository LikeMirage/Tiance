import type { ProjectFileCreateRequest, ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function createProjectFile(
  projectId: string,
  payload: ProjectFileCreateRequest,
) {
  return fetchJson<ProjectFileNode>(
    `/api/projects/${encodeURIComponent(projectId)}/files`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
