import type { ProjectFileCopyRequest, ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function copyProjectFile(projectId: string, payload: ProjectFileCopyRequest) {
  return fetchJson<ProjectFileNode>(
    `/api/projects/${encodeURIComponent(projectId)}/files/copy`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
