import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import type { DocumentTab, EditorTabId } from "../../../entities/editor/model/editorDocument";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";
import type { FileWorkspaceContentResponse } from "../../../entities/file-workspace/model/fileWorkspace";
import { HttpRequestError } from "../../../services/http/httpClient";

import {
  createProjectDocumentSource,
  type DocumentFileSourceRuntime,
} from "./documentFileSources";
import { buildWorkspaceFileTab, hydrateWorkspaceFileTab } from "./documentFileTabs";
import { resolveDocumentPreview } from "./documentPreviewResolver";
import { getPathName, makeTabId, normalizeWorkspacePath } from "./documentTabUtils";
import { getTextContentUnavailable } from "./documentTextLoadError";

type UseDocumentTabRestoreOptions = {
  registerFileSource: (runtime: DocumentFileSourceRuntime) => DocumentFileSourceRuntime;
  restoreRequestIdRef: MutableRefObject<number>;
  setActiveTabId: Dispatch<SetStateAction<EditorTabId | null>>;
  setTabs: Dispatch<SetStateAction<DocumentTab[]>>;
};

type RestoreWorkspaceTabsOptions = {
  fileContents?: Map<string, FileWorkspaceContentResponse>;
};

export function useDocumentTabRestore({
  registerFileSource,
  restoreRequestIdRef,
  setActiveTabId,
  setTabs,
}: UseDocumentTabRestoreOptions) {
  const restoreWorkspaceTabs = useCallback(async (
    sourceRuntime: DocumentFileSourceRuntime,
    filePaths: string[],
    activeFilePath: string | null,
    options: RestoreWorkspaceTabsOptions = {},
  ) => {
    const runtime = registerFileSource(sourceRuntime);
    const restoreRequestId = restoreRequestIdRef.current + 1;
    restoreRequestIdRef.current = restoreRequestId;
    const loadedTabs: DocumentTab[] = [];
    const api = runtime.getApi();
    const normalizedActiveFilePath = normalizeWorkspacePath(activeFilePath ?? "");

    for (const rawFilePath of filePaths) {
      const filePath = normalizeWorkspacePath(rawFilePath);
      if (!filePath) continue;
      const name = getPathName(filePath);
      const preview = resolveDocumentPreview({ id: filePath, name, path: filePath, kind: "file" } as ExplorerNode);

      const tab = buildWorkspaceFileTab(
        { id: filePath, name, path: filePath, kind: "file" } as ExplorerNode,
        runtime.source,
        filePath,
        preview,
      );
      if (preview.kind !== "text" || filePath !== normalizedActiveFilePath) {
        loadedTabs.push(tab);
        continue;
      }
      try {
        const res = options.fileContents?.get(filePath) ?? await api.readTextFile(filePath);
        if (restoreRequestIdRef.current !== restoreRequestId) return;
        loadedTabs.push(hydrateWorkspaceFileTab(tab, runtime.source, filePath, res));
      } catch (err) {
        if (restoreRequestIdRef.current !== restoreRequestId) return;
        if (err instanceof HttpRequestError && err.status === 404) {
          continue;
        }
        const unavailable = getTextContentUnavailable(err);
        if (unavailable) {
          loadedTabs.push({ ...tab, textContentUnavailable: unavailable });
          continue;
        }
        loadedTabs.push({
          ...tab,
          saveState: "error",
          saveError: err instanceof Error ? err.message : "读取文件失败。",
        });
      }
    }
    if (restoreRequestIdRef.current !== restoreRequestId) return;
    setTabs(loadedTabs);
    const requestedActiveId = activeFilePath
      ? makeTabId(runtime.source.key, activeFilePath)
      : null;
    const activeId = requestedActiveId && loadedTabs.some((tab) => tab.id === requestedActiveId)
      ? requestedActiveId
      : loadedTabs[0]?.id ?? null;
    setActiveTabId(activeId);
  }, [registerFileSource, restoreRequestIdRef, setActiveTabId, setTabs]);

  const restoreTabs = useCallback(async (
    projectId: string,
    filePaths: string[],
    activeFilePath: string | null,
    options: RestoreWorkspaceTabsOptions = {},
  ) => {
    await restoreWorkspaceTabs(
      createProjectDocumentSource(projectId),
      filePaths,
      activeFilePath,
      options,
    );
  }, [restoreWorkspaceTabs]);

  return {
    restoreTabs,
    restoreWorkspaceTabs,
  };
}
