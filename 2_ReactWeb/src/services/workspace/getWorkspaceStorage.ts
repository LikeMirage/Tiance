import { fetchJson } from "../http/httpClient";

export type WorkspaceStorage = {
  total_bytes: number;
  database_bytes: number;
  other_bytes: number;
  complete: boolean;
  sampled_at: string;
};

export function getWorkspaceStorage(signal: AbortSignal) {
  return fetchJson<WorkspaceStorage>("/api/workspace/storage", { cache: "no-store", signal });
}
