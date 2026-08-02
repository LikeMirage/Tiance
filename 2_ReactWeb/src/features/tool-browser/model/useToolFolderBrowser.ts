import type { UseToolFolderBrowserResult } from "./toolBrowserTypes";
import { useToolFolderBrowserController } from "./useToolFolderBrowserController";

export function useToolFolderBrowser(
  toolsetId: string | null,
  folderId: string | null,
  options: { initialExpandedPaths?: string[] } = {},
): UseToolFolderBrowserResult {
  return useToolFolderBrowserController(toolsetId, folderId, options);
}
