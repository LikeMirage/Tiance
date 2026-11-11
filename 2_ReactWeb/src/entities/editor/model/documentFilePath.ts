import type { DocumentFileSource } from "./editorDocument";

// Local sources identify a filesystem anchor (C:/, //server/share/, or /).
// Tab file paths stay relative, just as they do for project sources.
export function documentDisplayPath(source: DocumentFileSource | null, path: string): string {
  return source?.kind === "local" ? `${source.id.replace(/\/+$/, "")}/${path}` : path;
}
