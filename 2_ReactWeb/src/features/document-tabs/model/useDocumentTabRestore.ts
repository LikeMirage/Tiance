import { useCallback, useEffect, useRef, type MutableRefObject } from "react";

import type { DocumentTab, EditorTabId, WorkspaceTabEntry } from "../../../entities/editor/model/editorDocument";
import type { ExplorerNode } from "../../../entities/explorer-node/model/explorerNode";
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
  replaceWorkspaceFiles: (files: DocumentTab[], activeFileId: EditorTabId | null, entries?: WorkspaceTabEntry[]) => EditorTabId | null;
};

type RestoreWorkspaceTabsOptions = {
  entries?: WorkspaceTabEntry[] | null;
  overviewOnly?: boolean;
};

export function useDocumentTabRestore({
  registerFileSource,
  restoreRequestIdRef,
  replaceWorkspaceFiles,
}: UseDocumentTabRestoreOptions) {
  const restoreControllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => restoreControllerRef.current?.abort(), []);
  const restoreWorkspaceTabs = useCallback(async (
    sourceRuntime: DocumentFileSourceRuntime,
    filePaths: string[],
    activeFilePath: string | null,
    options: RestoreWorkspaceTabsOptions = {},
  ) => {
    restoreControllerRef.current?.abort();
    const controller = new AbortController();
    restoreControllerRef.current = controller;
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
      if (options.overviewOnly || preview.kind !== "text" || filePath !== normalizedActiveFilePath) {
        loadedTabs.push(tab);
        continue;
      }
      try {
        const res = await api.readTextFile(filePath, { signal: controller.signal });
        if (restoreRequestIdRef.current !== restoreRequestId) return;
        loadedTabs.push(hydrateWorkspaceFileTab(tab, runtime.source, filePath, res));
      } catch (err) {
        if (controller.signal.aborted) return;
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
    const requestedActiveId = activeFilePath
      ? makeTabId(runtime.source.key, activeFilePath)
      : null;
    const activeId = requestedActiveId && loadedTabs.some((tab) => tab.id === requestedActiveId)
      ? requestedActiveId
      : loadedTabs[0]?.id ?? null;
    return replaceWorkspaceFiles(loadedTabs, options.overviewOnly ? null : activeId, options.entries ?? undefined);
  }, [registerFileSource, restoreRequestIdRef, replaceWorkspaceFiles]);

  const restoreTabs = useCallback(async (
    projectId: string,
    filePaths: string[],
    activeFilePath: string | null,
    options: RestoreWorkspaceTabsOptions = {},
  ) => {
    return restoreWorkspaceTabs(
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
