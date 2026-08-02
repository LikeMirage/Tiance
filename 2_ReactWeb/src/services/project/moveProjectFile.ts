import type { ProjectFileMoveRequest, ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function moveProjectFile(projectId: string, payload: ProjectFileMoveRequest) {
  return fetchJson<ProjectFileNode>(
    `/api/projects/${encodeURIComponent(projectId)}/files/move`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
