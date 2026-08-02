import { useCallback, useMemo } from "react";

import type { FileWorkspaceMutation } from "../../../entities/file-workspace/model/fileWorkspace";
import type { FileWorkspaceBrowserNode } from "../../file-workspace/model/fileWorkspaceBrowserTreeModel";
import {
  publishProjectFileMutation,
  subscribeProjectFileMutations,
} from "../../../entities/project/model/projectFileMutation";
import { useFileWorkspaceBrowserController } from "../../file-workspace/model/useFileWorkspaceBrowserController";
import { createProjectFileWorkspaceApi } from "../../../services/project/projectFileWorkspaceApi";
import { watchProjectFileEvents } from "../../../services/project/watchProjectFileEvents";
import type { UseProjectBrowserResult } from "./projectBrowserTypes";

export function useProjectBrowserController(
  projectId: string | null,
  options: {
    initialExpandedPaths?: string[];
    initialTreeData?: FileWorkspaceBrowserNode[];
  } = {},
): UseProjectBrowserResult {
  const fileWorkspaceApi = useMemo(
    () => (projectId ? createProjectFileWorkspaceApi(projectId) : null),
    [projectId],
  );
  const workspaceKey = fileWorkspaceApi?.workspaceKey ?? null;

  const watchFileEvents = useCallback((handlers: { onChanged: (paths: string[]) => void }) => {
    if (!projectId) return () => undefined;
    return watchProjectFileEvents(projectId, handlers);
  }, [projectId]);

  const subscribeMutations = useCallback((handler: (mutation: FileWorkspaceMutation) => void) => {
    if (!projectId || !workspaceKey) return () => undefined;
    return subscribeProjectFileMutations((mutation) => {
      if (mutation.projectId !== projectId) return;
      if (mutation.action === "delete") {
        handler({
          action: "delete",
          path: mutation.path,
          sourceId: mutation.sourceId,
          workspaceKey,
        });
        return;
      }
      if (mutation.action === "move") {
        handler({
          action: "move",
          previousPath: mutation.previousPath,
          node: mutation.node,
          sourceId: mutation.sourceId,
          workspaceKey,
        });
        return;
      }
      handler({
        action: "upsert",
        node: mutation.node,
        sourceId: mutation.sourceId,
        workspaceKey,
      });
    });
  }, [projectId, workspaceKey]);

  const publishMutation = useCallback((mutation: FileWorkspaceMutation) => {
    if (!projectId || mutation.workspaceKey !== workspaceKey) return;
    if (mutation.action === "delete") {
      publishProjectFileMutation({
        action: "delete",
        path: mutation.path,
        projectId,
        sourceId: mutation.sourceId,
      });
      return;
    }
    if (mutation.action === "move") {
      publishProjectFileMutation({
        action: "move",
        previousPath: mutation.previousPath,
        node: mutation.node,
        projectId,
        sourceId: mutation.sourceId,
      });
      return;
    }
    publishProjectFileMutation({
      node: mutation.node,
      projectId,
      sourceId: mutation.sourceId,
    });
  }, [projectId, workspaceKey]);

  return useFileWorkspaceBrowserController({
    fileWorkspaceApi,
    initialExpandedPaths: options.initialExpandedPaths,
    initialTreeData: options.initialTreeData,
    publishMutation,
    subscribeMutations,
    watchFileEvents,
  });
}
