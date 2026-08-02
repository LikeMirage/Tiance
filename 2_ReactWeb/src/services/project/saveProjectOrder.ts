import type { ProjectOrderResponse } from "./getProjectOrder";
import { fetchJson } from "../http/httpClient";

export function saveProjectOrder(projectIds: string[]) {
  return fetchJson<ProjectOrderResponse>("/api/projects/order", {
    method: "PUT",
    body: JSON.stringify({ project_ids: projectIds }),
  });
}
