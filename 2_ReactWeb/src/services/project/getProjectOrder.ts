import { fetchJson } from "../http/httpClient";

export type ProjectOrderResponse = {
  count: number;
  project_ids: string[];
};

export function getProjectOrder() {
  return fetchJson<ProjectOrderResponse>("/api/projects/order");
}
