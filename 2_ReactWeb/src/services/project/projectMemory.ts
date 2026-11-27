import type {
  ProjectMemoryListResponse,
  ProjectMemoryOperationInput,
  ProjectMemoryOperationResponse,
  ProjectMemoryScope,
} from "../../entities/project-memory/model/projectMemory";
import { fetchJson } from "../http/httpClient";
import { notifyMemoryChanged } from "../memory/memoryChanges";

export function getProjectMemory(
  projectId: string,
  {
    page,
    pageSize = 50,
    query = "",
    scope,
    signal,
  }: {
    page?: number;
    pageSize?: number;
    query?: string;
    scope: ProjectMemoryScope;
    signal?: AbortSignal;
  },
) {
  const params = new URLSearchParams({
    page_size: String(pageSize),
    query,
    scope,
  });
  if (page !== undefined) params.set("page", String(page));
  return fetchJson<ProjectMemoryListResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory?${params.toString()}`,
    { signal },
  );
}

export async function applyProjectMemoryOperation(
  projectId: string,
  input: ProjectMemoryOperationInput,
) {
  const result = await fetchJson<ProjectMemoryOperationResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/memory/operations`,
    {
      body: JSON.stringify(input),
      method: "POST",
    },
  );
  notifyMemoryChanged(projectId, input);
  return result;
}
