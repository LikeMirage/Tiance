import { env } from "../../shared/config/env";
import { watchEventSocket } from "../http/watchEventSocket";

export type ProjectWorkspaceEvent = {
  kind: "ready" | "changed";
  paths?: string[];
};

export function watchProjectWorkspaceEvents(onChanged: (paths: string[]) => void) {
  let needsReconcile = false;
  return watchEventSocket(`${env.apiBaseUrl}/api/projects/events`, {
    onMessage: (data) => {
      const payload = parseProjectWorkspaceEvent(data);
      if (payload?.kind === "changed") onChanged(payload.paths ?? []);
      if (payload?.kind === "ready" && needsReconcile) {
        needsReconcile = false;
        onChanged([]);
      }
    },
    onReconnect: () => { needsReconcile = true; },
    onDisconnect: () => { needsReconcile = true; },
  });
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
