import { env } from "../../shared/config/env";

const ACTIVE_THEME_SETTINGS_PATH = "theme-settings.json";

export type ThemeWorkspaceEvent = {
  kind: "ready" | "changed";
  paths?: string[];
};

export function watchThemeWorkspaceEvents(onChanged: (paths: string[]) => void) {
  const source = new EventSource(`${env.apiBaseUrl}/api/themes/events`);

  source.onmessage = (event) => {
    const payload = parseThemeWorkspaceEvent(event.data);
    if (!payload || payload.kind !== "changed") return;
    onChanged(payload.paths ?? []);
  };

  return () => source.close();
}

export function shouldRefreshThemeWorkspace(paths: string[]): boolean {
  return paths.length === 0
    || paths.some((path) => path !== ACTIVE_THEME_SETTINGS_PATH);
}

export function parseThemeWorkspaceEvent(data: string): ThemeWorkspaceEvent | null {
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
