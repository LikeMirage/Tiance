import { fetchJson } from "../http/httpClient";

export type SpeechStatus = {
  id: string;
  status: "created" | "uploading" | "ready" | "recognizing" | "completed" | "failed" | "cancelled";
  text?: string;
  error?: string;
  recording_path?: string;
};

export function speechEndpoint(projectId: string, sessionId: string) {
  return `/api/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(sessionId)}/recordings`;
}

export const conversationSpeech = {
  create: (path: string) => fetchJson<SpeechStatus>(path, { method: "POST" }),
  upload: (path: string, blob: Blob) => fetchJson<SpeechStatus>(`${path}/audio`, {
    method: "PUT", body: blob, headers: { "Content-Type": blob.type },
  }),
  start: (path: string, signal: AbortSignal) => fetchJson<SpeechStatus>(`${path}/recognize`, { method: "POST", signal }),
  status: (path: string, signal: AbortSignal) => fetchJson<SpeechStatus>(path, { signal }),
  cancel: (path: string) => fetchJson<SpeechStatus>(path, { method: "DELETE", keepalive: true }),
};
