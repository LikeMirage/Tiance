import type {
  Project,
  ProjectCreateRequest,
} from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function createProject(payload: ProjectCreateRequest = {}) {
  return fetchJson<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
