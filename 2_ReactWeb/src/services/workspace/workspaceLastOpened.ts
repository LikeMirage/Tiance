import { fetchJson } from "../http/httpClient";

export type WorkspaceLastOpenedResponse = {
  category_id: string | null;
  category_selections: Record<string, WorkspaceCategorySelection>;
  project_id: string | null;
  session_id: string | null;
  updated_at: string | null;
};

export type WorkspaceCategorySelection = {
  category_id: string;
  project_id: string | null;
  session_id: string | null;
  updated_at: string | null;
};

export type WorkspaceLastOpenedSaveInput = {
  category_id?: string | null;
  project_id?: string | null;
  session_id?: string | null;
};

const workspaceLastOpenedEvents = new EventTarget();
let workspaceLastOpenedSaveRequestId = 0;
let workspaceLastOpenedSaveQueue: Promise<void> = Promise.resolve();

export function getWorkspaceLastOpened() {
  return fetchJson<WorkspaceLastOpenedResponse>("/api/workspace/last-opened");
}

export async function saveWorkspaceLastOpened(input: WorkspaceLastOpenedSaveInput) {
  const requestId = workspaceLastOpenedSaveRequestId + 1;
  workspaceLastOpenedSaveRequestId = requestId;
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
  const response = await request;
  if (workspaceLastOpenedSaveRequestId === requestId) {
    dispatchWorkspaceLastOpenedChanged(response);
  }
  return response;
}

export function listenWorkspaceLastOpenedChanged(
  handler: (state: WorkspaceLastOpenedResponse) => void,
) {
  const listener = (event: Event) => {
    handler((event as CustomEvent<WorkspaceLastOpenedResponse>).detail);
  };
  workspaceLastOpenedEvents.addEventListener("workspace-last-opened-changed", listener);
  return () => {
    workspaceLastOpenedEvents.removeEventListener("workspace-last-opened-changed", listener);
  };
}

function dispatchWorkspaceLastOpenedChanged(state: WorkspaceLastOpenedResponse) {
  workspaceLastOpenedEvents.dispatchEvent(
    new CustomEvent("workspace-last-opened-changed", { detail: state }),
  );
}
