import type {
  ProjectMemoryListResponse,
  ProjectMemoryOperationInput,
  ProjectMemoryOperationResponse,
  ProjectMemoryScope,
} from "../../entities/project-memory/model/projectMemory";
import { fetchJson } from "../http/httpClient";

export function getProjectMemory(
  projectId: string,
  {
    limit = 100,
    query = "",
    scope,
    signal,
  }: {
    limit?: number;
    query?: string;
    scope: ProjectMemoryScope;
    signal?: AbortSignal;
  },
) {
  const params = new URLSearchParams({
    limit: String(limit),
    query,
    scope,
  });
  return fetchJson<ProjectMemoryListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory?${params.toString()}`,
    { signal },
  );
}

export function applyProjectMemoryOperation(
  projectId: string,
  input: ProjectMemoryOperationInput,
) {
  return fetchJson<ProjectMemoryOperationResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory/operations`,
    {
      body: JSON.stringify(input),
      method: "POST",
    },
  );
}
