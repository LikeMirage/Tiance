import { fetchJson } from "../http/httpClient";

export type GithubSyncCollection =
  | "project"
  | "knowledge"
  | "experience"
  | "role"
  | "theme"
  | "tool"
  | "provider";

export type GithubSyncRepository = {
  id: number;
  fullName: string;
  private: boolean;
  defaultBranch: string;
  canPush: boolean;
};

export type GithubSyncBinding = {
  collection: GithubSyncCollection;
  repository: string;
  branch: string;
  remotePath: string;
  updatedAt: string;
};

export type GithubSyncOverview = {
  collection: GithubSyncCollection;
  connected: boolean;
  binding: GithubSyncBinding | null;
  repositories: GithubSyncRepository[];
  authorizationUrl: string;
};

export type GithubSyncChange = {
  path: string;
  kind: "add" | "update" | "delete";
  size: number;
};

export type GithubSyncPlan = {
  planId: string;
  collection: GithubSyncCollection;
  direction: "push" | "pull";
  repository: string;
  branch: string;
  remotePath: string;
  remoteHeadSha: string | null;
  changes: GithubSyncChange[];
  additions: number;
  updates: number;
  deletions: number;
  createdAt: string;
};

export type GithubSyncApplyResult = {
  ok: true;
  collection: GithubSyncCollection;
  direction: "push" | "pull";
  repository: string;
  branch: string;
  commitSha: string | null;
  changedFiles: number;
  message: string;
};

export function getGithubSyncOverview(collection: GithubSyncCollection, signal?: AbortSignal) {
  return fetchJson<GithubSyncOverview>(`/api/github/sync/${collection}`, { signal });
}

export function saveGithubSyncBinding(
  collection: GithubSyncCollection,
  input: { repository: string; branch: string; remotePath: string },
  signal?: AbortSignal,
) {
  return fetchJson<GithubSyncBinding>(`/api/github/sync/${collection}/binding`, {
    body: JSON.stringify(input),
    method: "PUT",
    signal,
  });
}

export function deleteGithubSyncBinding(collection: GithubSyncCollection, signal?: AbortSignal) {
  return fetchJson<{ ok: true }>(`/api/github/sync/${collection}/binding`, {
    method: "DELETE",
    signal,
  });
}

export function createGithubSyncPlan(
  collection: GithubSyncCollection,
  direction: "push" | "pull",
  signal?: AbortSignal,
) {
  return fetchJson<GithubSyncPlan>("/api/github/sync/plans/create", {
    body: JSON.stringify({ collection, direction }),
    method: "POST",
    signal,
  });
}

export function applyGithubSyncPlan(
  planId: string,
  commitMessage: string | null,
  signal?: AbortSignal,
) {
  return fetchJson<GithubSyncApplyResult>(
    `/api/github/sync/plans/${encodeURIComponent(planId)}/apply`,
    {
      body: JSON.stringify({ commitMessage }),
      method: "POST",
      signal,
    },
  );
}

