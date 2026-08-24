import type { DesktopPathEntry } from "../../../shared/types/desktopShell";
import { isDesktopPathEntry } from "./desktopPathEntry";

export class DesktopFilePickerUnavailableError extends Error {
  constructor() {
    super("Desktop file picker is unavailable.");
    this.name = "DesktopFilePickerUnavailableError";
  }
}

export async function selectDesktopFiles(): Promise<DesktopPathEntry[]> {
  const api = window.pywebview?.api;
  if (typeof api?.select_external_files !== "function") {
    throw new DesktopFilePickerUnavailableError();
  }

  const entries = await api.select_external_files();
  if (
    !Array.isArray(entries)
    || !entries.every((entry) => isDesktopPathEntry(entry) && entry.kind === "file")
  ) {
    throw new Error("Invalid desktop file picker response.");
  }
  return entries;
}
