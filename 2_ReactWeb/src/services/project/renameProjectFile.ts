import type { ProjectFileNode } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function renameProjectFile(
  projectId: string,
  path: string,
  name: string,
) {
  return fetchJson<ProjectFileNode>(
    `/api/projects/${encodeURIComponent(projectId)}/files`,
    {
      method: "PATCH",
      body: JSON.stringify({ path, name }),
    },
  );
}
