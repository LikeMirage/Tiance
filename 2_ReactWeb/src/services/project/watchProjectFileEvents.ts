import { env } from "../../shared/config/env";

type ProjectFileWatchEvent = {
  kind: "ready" | "changed" | "overflow" | "unavailable";
  paths?: string[];
};

export type ProjectFileWatchHandlers = {
  onChanged: (paths: string[]) => void;
  onOverflow?: () => void;
  onStatusChanged?: (available: boolean) => void;
  onError?: () => void;
};

type ProjectFileWatchChannel = {
  handlers: Set<ProjectFileWatchHandlers>;
  source: EventSource;
};

const projectFileWatchChannels = new Map<string, ProjectFileWatchChannel>();

export function watchProjectFileEvents(
  projectId: string,
  handlers: ProjectFileWatchHandlers,
) {
  let channel = projectFileWatchChannels.get(projectId);
  if (!channel) {
    const source = new EventSource(
      `${env.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/files/events`,
    );
    channel = { handlers: new Set(), source };
    projectFileWatchChannels.set(projectId, channel);

    source.onmessage = (event) => {
      const payload = parseProjectFileWatchEvent(event.data);
      if (!payload) return;
      for (const subscriber of channel?.handlers ?? []) {
        if (payload.kind === "changed") {
          subscriber.onStatusChanged?.(true);
          subscriber.onChanged(payload.paths ?? []);
        } else if (payload.kind === "overflow") {
          subscriber.onStatusChanged?.(true);
          subscriber.onOverflow?.();
        } else if (payload.kind === "ready") {
          subscriber.onStatusChanged?.(true);
        } else if (payload.kind === "unavailable") {
          subscriber.onStatusChanged?.(false);
        }
      }
    };
    source.onerror = () => {
      for (const subscriber of channel?.handlers ?? []) {
        subscriber.onStatusChanged?.(false);
        subscriber.onError?.();
      }
    };
  }

  channel.handlers.add(handlers);
  return () => {
    const activeChannel = projectFileWatchChannels.get(projectId);
    if (!activeChannel) return;
    activeChannel.handlers.delete(handlers);
    if (activeChannel.handlers.size > 0) return;
    activeChannel.source.close();
    projectFileWatchChannels.delete(projectId);
  };
}

function parseProjectFileWatchEvent(data: string): ProjectFileWatchEvent | null {
  try {
    const payload = JSON.parse(data) as ProjectFileWatchEvent;
    return payload && typeof payload.kind === "string" ? payload : null;
  } catch {
    return null;
  }
}
