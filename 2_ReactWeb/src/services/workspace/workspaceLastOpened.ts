import { fetchJson } from "../http/httpClient";

export type WorkspaceLastOpenedResponse = {
  category_id: string | null;
  category_selections: Record<string, WorkspaceCategorySelection>;
  project_id: string | null;
  updated_at: string | null;
};

export type WorkspaceCategorySelection = {
  category_id: string;
  project_id: string | null;
  updated_at: string | null;
};

export type WorkspaceLastOpenedSaveInput = {
  category_id?: string | null;
  project_id?: string | null;
};

let workspaceLastOpenedSaveQueue: Promise<void> = Promise.resolve();

export function getWorkspaceLastOpened() {
  return fetchJson<WorkspaceLastOpenedResponse>("/api/workspace/last-opened");
}

export function saveWorkspaceLastOpened(input: WorkspaceLastOpenedSaveInput) {
  const request = workspaceLastOpenedSaveQueue.then(() =>
    fetchJson<WorkspaceLastOpenedResponse>("/api/workspace/last-opened", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  );
  workspaceLastOpenedSaveQueue = request.then(
    () => undefined,
    () => undefined,
  );
  return request;
}
