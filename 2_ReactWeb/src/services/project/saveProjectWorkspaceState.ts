import { fetchJson } from "../http/httpClient";
import { getProjectWorkspaceState, type WorkspaceStateResponse } from "./getProjectWorkspaceState";

const pendingWrites = new Map<string, Promise<WorkspaceStateResponse>>();

const pendingReads = new Map<string, Promise<WorkspaceStateResponse>>();

export async function finishWorkspaceWrites() {
  if (!pendingWrites.size) return;
  // Give queued tab preferences a chance to finish on exit even when the backend is slow.
  let timer: number | undefined;
  try {
    await Promise.race([
      Promise.allSettled(pendingWrites.values()),
      new Promise<void>(resolve => { timer = window.setTimeout(resolve, 2500); }),
    ]);
  } finally {
    window.clearTimeout(timer);
  }
}

export function readWorkspaceAfterWrites(projectId: string): Promise<WorkspaceStateResponse> {
  const pending = pendingWrites.get(projectId);
  if (pending) return pending.catch(() => readWorkspaceAfterWrites(projectId));
  const existing = pendingReads.get(projectId);
  if (existing) return existing;
  const read = getProjectWorkspaceState(projectId);
  pendingReads.set(projectId, read);
  const clear = () => { if (pendingReads.get(projectId) === read) pendingReads.delete(projectId); };
  void read.then(clear, clear);
  return read;
}

export function patchProjectWorkspaceState(
  projectId: string,
  payload: Partial<Omit<WorkspaceStateResponse, "project_id">>,
) {
  const body = JSON.stringify(payload);
  const write = () => fetchJson<WorkspaceStateResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/workspace-state`,
    { method: "PATCH", body, keepalive: new Blob([body]).size < 60_000, signal: AbortSignal.timeout(10_000) },
  );
  return queueWorkspaceStateRequest(projectId, write);
}

export function queueWorkspaceStateRequest<T extends WorkspaceStateResponse>(projectId: string, write: () => Promise<T>) {
  const previous = pendingWrites.get(projectId);
  pendingReads.delete(projectId);
  const request = previous ? previous.then(write, write) : write();
  pendingWrites.set(projectId, request);
  const clear = () => { if (pendingWrites.get(projectId) === request) pendingWrites.delete(projectId); };
  void request.then(clear, clear);
  return request;
}
