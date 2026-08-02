import type {
  DesktopExternalFileImportFailureReason,
  DesktopExternalFileImportResult,
  DesktopPathEntry,
} from "../../../shared/types/desktopShell";

const FAILURE_REASONS = new Set<DesktopExternalFileImportFailureReason>([
  "source_missing",
  "copy_failed",
]);

export class DesktopExternalFileImportUnavailableError extends Error {
  constructor() {
    super("Desktop external file import is unavailable.");
    this.name = "DesktopExternalFileImportUnavailableError";
  }
}

export async function importDesktopPathEntriesToWorkspace(
  entries: DesktopPathEntry[],
  destinationRoot: string,
): Promise<DesktopExternalFileImportResult> {
  const api = window.pywebview?.api;
  if (typeof api?.copy_external_entries_to_directory !== "function") {
    throw new DesktopExternalFileImportUnavailableError();
  }

  const sourcePaths = Array.from(new Set(entries.map((entry) => entry.path)));
  const result = await api.copy_external_entries_to_directory(sourcePaths, destinationRoot);
  if (!isDesktopExternalFileImportResult(result)) {
    throw new Error("Invalid desktop external file import response.");
  }
  return result;
}

function isDesktopExternalFileImportResult(
  value: unknown,
): value is DesktopExternalFileImportResult {
  if (!isRecord(value)) return false;
  if (!Array.isArray(value.imported) || !Array.isArray(value.failures)) return false;

  return value.imported.every((item) => (
    isRecord(item)
    && typeof item.name === "string"
    && typeof item.path === "string"
    && typeof item.sourcePath === "string"
  )) && value.failures.every((item) => (
    isRecord(item)
    && typeof item.name === "string"
    && typeof item.sourcePath === "string"
    && typeof item.reason === "string"
    && FAILURE_REASONS.has(item.reason as DesktopExternalFileImportFailureReason)
  ));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
