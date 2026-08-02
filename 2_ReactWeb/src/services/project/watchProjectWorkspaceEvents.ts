import { env } from "../../shared/config/env";

export type ProjectWorkspaceEvent = {
  kind: "ready" | "changed";
  paths?: string[];
};

export function watchProjectWorkspaceEvents(onChanged: (paths: string[]) => void) {
  const source = new EventSource(`${env.apiBaseUrl}/api/projects/events`);

  source.onmessage = (event) => {
    const payload = parseProjectWorkspaceEvent(event.data);
    if (!payload || payload.kind !== "changed") return;
    onChanged(payload.paths ?? []);
  };

  return () => source.close();
}

export function parseProjectWorkspaceEvent(data: string): ProjectWorkspaceEvent | null {
  try {
    const payload = JSON.parse(data) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
    const kind = (payload as { kind?: unknown }).kind;
    if (kind !== "ready" && kind !== "changed") return null;
    const paths = (payload as { paths?: unknown }).paths;
    if (paths !== undefined && (
      !Array.isArray(paths)
      || paths.some((path) => typeof path !== "string")
    )) return null;
    return { kind, paths: paths as string[] | undefined };
  } catch {
    return null;
  }
}
