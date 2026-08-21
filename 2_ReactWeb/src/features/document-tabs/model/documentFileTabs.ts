import type {
  DocumentFileSource,
  DocumentTab,
} from "../../../entities/editor/model/editorDocument";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";
import type { FileWorkspaceContentResponse } from "../../../entities/file-workspace/model/fileWorkspace";

import { isProjectFileSource } from "./documentFileSources";
import type { ResolvedPreview } from "./documentPreviewResolver";
import { getPathName, makeStandaloneTabId, makeTabId, normalizeWorkspacePath } from "./documentTabUtils";

export function buildWorkspaceFileTab(
  node: ExplorerNode,
  source: DocumentFileSource,
  filePath: string,
  preview: ResolvedPreview,
): DocumentTab {
  const isProjectSource = isProjectFileSource(source);
  const isText = preview.kind === "text";
  return {
    id: makeTabId(source.key, filePath),
    title: node.name,
    displayPath: filePath,
    kind: preview.kind,
    languageId: preview.languageId,
    content: "",
    savedContent: "",
    textContentAccessedAt: null,
    textContentLoaded: !isText,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: source,
    filePath,
    projectId: source.projectId ?? (isProjectSource ? source.id : null),
    projectFilePath: source.projectId || isProjectSource ? filePath : null,
    assetVersion: preview.kind === "text" ? null : Date.now(),
    mtimeMs: typeof node.mtimeMs === "number" ? node.mtimeMs : null,
    externalChange: null,
  };
}

export function hydrateWorkspaceFileTab(
  tab: DocumentTab,
  source: DocumentFileSource,
  requestedFilePath: string,
  response: FileWorkspaceContentResponse,
): DocumentTab {
  const resolvedPath = normalizeWorkspacePath(response.path || requestedFilePath);
  return {
    ...tab,
    id: makeTabId(source.key, resolvedPath),
    title: getPathName(resolvedPath),
    displayPath: resolvedPath,
    filePath: resolvedPath,
    projectFilePath:
      source.projectId || isProjectFileSource(source)
        ? resolvedPath
        : tab.projectFilePath,
    content: response.content,
    savedContent: response.content,
    textContentAccessedAt: Date.now(),
    textContentLoaded: true,
    textContentUnavailable: null,
    assetVersion: null,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    mtimeMs: response.mtime_ms,
    externalChange: null,
  };
}

export function buildStandaloneFileTab(
  node: ExplorerNode,
  filePath: string,
  preview: ResolvedPreview,
): DocumentTab {
  return {
    id: makeStandaloneTabId(filePath),
    title: node.name,
    displayPath: filePath,
    kind: preview.kind,
    languageId: preview.languageId,
    content: "",
    savedContent: "",
    textContentAccessedAt: null,
    textContentLoaded: true,
    isDirty: false,
    isMissing: false,
    saveState: "idle",
    saveError: null,
    fileSource: null,
    filePath,
    projectId: null,
    projectFilePath: null,
    assetVersion: preview.kind === "text" ? null : Date.now(),
    mtimeMs: null,
    externalChange: null,
  };
}
