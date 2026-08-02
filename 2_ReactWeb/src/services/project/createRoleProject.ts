import type {
  Project,
  RoleProjectCreateRequest,
} from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function createRoleProject(payload: RoleProjectCreateRequest = {}) {
  return fetchJson<Project>("/api/projects/roles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
