import type { DesktopPathEntry } from "../../../shared/types/desktopShell";
import { isDesktopPathEntry } from "./desktopPathEntry";

export async function readDesktopClipboardPathEntries(): Promise<DesktopPathEntry[]> {
  const api = window.pywebview?.api;
  if (typeof api?.get_clipboard_path_entries !== "function") return [];

  const entries = await api.get_clipboard_path_entries();
  if (!Array.isArray(entries)) return [];
  return entries.filter(isDesktopPathEntry);
}

export async function writeDesktopClipboardPathEntries(paths: string[]): Promise<boolean> {
  const api = window.pywebview?.api;
  if (typeof api?.set_clipboard_path_entries !== "function") return false;
  return api.set_clipboard_path_entries(paths);
}
