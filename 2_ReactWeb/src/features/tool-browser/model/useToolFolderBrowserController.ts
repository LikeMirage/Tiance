import { useCallback, useMemo } from "react";

import type { FileWorkspaceMutation } from "../../../entities/file-workspace/model/fileWorkspace";
import {
  publishToolFolderFileMutation,
  subscribeToolFolderFileMutations,
  toFileWorkspaceMutation,
} from "../../../entities/tool/model/toolFolderFileMutation";
import { useFileWorkspaceBrowserController } from "../../file-workspace/model/useFileWorkspaceBrowserController";
import { createToolFolderFileWorkspaceApi } from "../../../services/tools/toolFolderFileWorkspaceApi";
import type { UseToolFolderBrowserResult } from "./toolBrowserTypes";

export function useToolFolderBrowserController(
  toolsetId: string | null,
  folderId: string | null,
  options: { initialExpandedPaths?: string[] } = {},
): UseToolFolderBrowserResult {
  const fileWorkspaceApi = useMemo(
    () =>
      toolsetId && folderId
        ? createToolFolderFileWorkspaceApi(toolsetId, folderId)
        : null,
    [folderId, toolsetId],
  );
  const workspaceKey = fileWorkspaceApi?.workspaceKey ?? null;

  const subscribeMutations = useCallback((handler: (mutation: FileWorkspaceMutation) => void) => {
    if (!toolsetId || !folderId || !workspaceKey) return () => undefined;
    return subscribeToolFolderFileMutations((mutation) => {
      if (mutation.toolsetId !== toolsetId || mutation.folderId !== folderId) return;
      handler(toFileWorkspaceMutation(mutation));
    });
  }, [folderId, toolsetId, workspaceKey]);

  const publishMutation = useCallback((mutation: FileWorkspaceMutation) => {
    if (!toolsetId || !folderId || mutation.workspaceKey !== workspaceKey) return;
    if (mutation.action === "delete") {
      publishToolFolderFileMutation({
        action: "delete",
        folderId,
        path: mutation.path,
        sourceId: mutation.sourceId,
        toolsetId,
      });
      return;
    }
    if (mutation.action === "move") {
      publishToolFolderFileMutation({
        action: "move",
        folderId,
        previousPath: mutation.previousPath,
        node: mutation.node,
        sourceId: mutation.sourceId,
        toolsetId,
      });
      return;
    }
    publishToolFolderFileMutation({
      action: "upsert",
      folderId,
      node: mutation.node,
      sourceId: mutation.sourceId,
      toolsetId,
    });
  }, [folderId, toolsetId, workspaceKey]);

  return useFileWorkspaceBrowserController({
    fileWorkspaceApi,
    initialExpandedPaths: options.initialExpandedPaths,
    publishMutation,
    subscribeMutations,
  });
}
