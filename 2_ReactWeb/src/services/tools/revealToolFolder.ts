import { revealInFileExplorer } from "../desktop/fileExplorer";

export function revealToolFolder(toolsetId: string, folderId: string) {
  return revealInFileExplorer(
    `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/reveal`,
    { method: "POST" },
  );
}
