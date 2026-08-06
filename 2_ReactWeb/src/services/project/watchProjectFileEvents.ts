import { env } from "../../shared/config/env";

type ProjectFileWatchEvent = {
  kind: "ready" | "changed";
  paths?: string[];
};

type ProjectFileWatchHandlers = {
  onChanged: (paths: string[]) => void;
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
      if (!payload || payload.kind !== "changed") return;
      const changedPaths = payload.paths ?? [];
      for (const subscriber of channel?.handlers ?? []) {
        subscriber.onChanged(changedPaths);
      }
    };
    source.onerror = () => {
      for (const subscriber of channel?.handlers ?? []) {
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
