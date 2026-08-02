import type {
  ProjectFileOpenExternalRequest,
  ProjectFileOpenExternalResponse,
} from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function openProjectFileExternal(
  projectId: string,
  payload: ProjectFileOpenExternalRequest,
) {
  return fetchJson<ProjectFileOpenExternalResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/files/open-external`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
