import { fetchJson } from "../http/httpClient";

export type GithubRepositorySummary = {
  id: number;
  fullName: string;
  private: boolean;
  defaultBranch: string;
  canPush: boolean;
};

export type GithubConnectionStatus = {
  connected: boolean;
  account: {
    login: string;
    name: string | null;
    avatarUrl: string;
    profileUrl: string;
  } | null;
  repositories: GithubRepositorySummary[];
  permissions: Record<string, string>;
  missingPermissions: string[];
  requiresReauthorization: boolean;
  authorizationUrl: string;
};

export type GithubDeviceFlow = {
  flowId: string;
  userCode: string;
  verificationUri: string;
  expiresIn: number;
  interval: number;
};

export type GithubDeviceFlowPoll = {
  status: "pending" | "slow_down" | "completed";
  retryAfter: number | null;
  connection: GithubConnectionStatus | null;
};

export function getGithubConnection(signal?: AbortSignal) {
  return fetchJson<GithubConnectionStatus>("/api/github/connection", { signal });
}

export function startGithubDeviceFlow(signal?: AbortSignal) {
  return fetchJson<GithubDeviceFlow>("/api/github/device-flow", {
    method: "POST",
    signal,
  });
}

export function pollGithubDeviceFlow(flowId: string, signal?: AbortSignal) {
  return fetchJson<GithubDeviceFlowPoll>("/api/github/device-flow/poll", {
    method: "POST",
    body: JSON.stringify({ flowId }),
    signal,
  });
}

export function logoutGithub(signal?: AbortSignal) {
  return fetchJson<{ connected: false }>("/api/github/connection", {
    method: "DELETE",
    signal,
  });
}
