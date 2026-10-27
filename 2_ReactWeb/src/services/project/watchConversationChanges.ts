import { env } from "../../shared/config/env";
import { fetchJson } from "../http/httpClient";
import { watchEventSocket } from "../http/watchEventSocket";

export type ConversationMessageState = { revision: number; reset_revision: number; project_revision: number };
const base = (project: string, session: string) =>
  `/api/projects/${encodeURIComponent(project)}/conversations/${encodeURIComponent(session)}`;

export function getConversationMessageState(project: string, session: string, signal?: AbortSignal) {
  return fetchJson<ConversationMessageState>(`${base(project, session)}/messages/state`, { signal });
}

export function watchConversationChanges(project: string, session: string, handlers: {
  onChange: (state: ConversationMessageState, ready: boolean) => void;
  onDisconnect: () => void;
}) {
  return watchEventSocket(`${env.apiBaseUrl}${base(project, session)}/events`, {
    onDisconnect: handlers.onDisconnect,
    onMessage(data) {
      let event;
      try { event = JSON.parse(data); } catch { return; }
      if (!event || typeof event !== "object") return;
      if ((event.kind === "ready" || event.kind === "changed") &&
          [event.revision, event.reset_revision, event.project_revision].every(Number.isSafeInteger)) {
        handlers.onChange(event, event.kind === "ready");
      }
    },
  });
}
