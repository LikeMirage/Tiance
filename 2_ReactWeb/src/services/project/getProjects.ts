import type { ProjectListResponse } from "../../entities/project/model/project";
import { fetchJson } from "../http/httpClient";

export function getProjects() {
  return fetchJson<ProjectListResponse>("/api/projects");
}
