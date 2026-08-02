import { env } from "../../shared/config/env";

type ProjectFileWatchEvent = {
  kind: "ready" | "changed";
  paths?: string[];
};

type ProjectFileWatchHandlers = {
  onChanged: (paths: string[]) => void;
  onError?: () => void;
};

export function watchProjectFileEvents(
  projectId: string,
  handlers: ProjectFileWatchHandlers,
) {
  const source = new EventSource(
    `${env.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/files/events`,
  );

  source.onmessage = (event) => {
    const payload = parseProjectFileWatchEvent(event.data);
    if (!payload || payload.kind !== "changed") return;
    handlers.onChanged(payload.paths ?? []);
  };
  source.onerror = () => {
    handlers.onError?.();
  };

  return () => source.close();
}

function parseProjectFileWatchEvent(data: string): ProjectFileWatchEvent | null {
  try {
    const payload = JSON.parse(data) as ProjectFileWatchEvent;
    return payload && typeof payload.kind === "string" ? payload : null;
  } catch {
    return null;
  }
}
