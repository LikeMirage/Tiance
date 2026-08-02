import type { FileWorkspaceBrowserNode } from "../../file-workspace/model/fileWorkspaceBrowserTreeModel";
import type { UseProjectBrowserResult } from "./projectBrowserTypes";
import { useProjectBrowserController } from "./useProjectBrowserController";

export function useProjectBrowser(
  projectId: string | null,
  options: {
    initialExpandedPaths?: string[];
    initialTreeData?: FileWorkspaceBrowserNode[];
  } = {},
): UseProjectBrowserResult {
  return useProjectBrowserController(projectId, options);
}
