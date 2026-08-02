import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { parseToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";
import { openProjectFileExternal } from "../../../services/project/openProjectFileExternal";
import { revealProjectFile } from "../../../services/project/revealProjectFile";
import {
  openToolFolderFileExternal,
  revealToolFolderFile,
} from "../../../services/tools/toolFolderFileWorkspaceApi";

export type DocumentExternalFileActions = {
  openNativeFile: (() => Promise<void>) | null;
  revealFile: (() => Promise<void>) | null;
};

export function createDocumentExternalFileActions(tab: DocumentTab | null): DocumentExternalFileActions {
  const source = tab?.fileSource ?? null;
  const filePath = normalizeActionFilePath(tab?.filePath);
  if (!source || !filePath) {
    return { openNativeFile: null, revealFile: null };
  }

  if (source.kind === "project") {
    return {
      openNativeFile: async () => {
        await openProjectFileExternal(source.id, { path: filePath });
      },
      revealFile: () => revealProjectFile(source.id, { path: filePath }),
    };
  }

  if (source.kind === "tool-folder") {
    const folder = parseToolFolderWorkspaceKey(source.key);
    if (!folder) {
      return { openNativeFile: null, revealFile: null };
    }
    return {
      openNativeFile: async () => {
        await openToolFolderFileExternal(folder.toolsetId, folder.folderId, { path: filePath });
      },
      revealFile: () => revealToolFolderFile(folder.toolsetId, folder.folderId, { path: filePath }),
    };
  }

  return { openNativeFile: null, revealFile: null };
}

function normalizeActionFilePath(path: string | null | undefined) {
  return path?.replace(/\\/g, "/").replace(/^\/+/, "").trim() || "";
}
