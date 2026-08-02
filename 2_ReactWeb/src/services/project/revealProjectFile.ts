import type { ProjectFileRevealRequest } from "../../entities/project/model/project";
import { fetchNoContent } from "../http/httpClient";

export function revealProjectFile(projectId: string, payload: ProjectFileRevealRequest) {
  return fetchNoContent(
    `/api/projects/${encodeURIComponent(projectId)}/files/reveal`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
