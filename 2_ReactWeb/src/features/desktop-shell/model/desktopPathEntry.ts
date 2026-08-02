import type { DesktopPathEntry } from "../../../shared/types/desktopShell";

export function isDesktopPathEntry(value: unknown): value is DesktopPathEntry {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entry = value as Record<string, unknown>;
  return (
    (entry.kind === "file" || entry.kind === "folder") &&
    typeof entry.name === "string" &&
    entry.name.trim().length > 0 &&
    typeof entry.path === "string" &&
    entry.path.trim().length > 0
  );
}
