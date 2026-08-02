import { fetchJson } from "../http/httpClient";

export interface ServerHealth {
  name: string;
  status: string;
  environment: string;
  version: string;
  docs_url: string;
  instance_id?: string | null;
}

export function getServerHealth() {
  return fetchJson<ServerHealth>("/api/health");
}
