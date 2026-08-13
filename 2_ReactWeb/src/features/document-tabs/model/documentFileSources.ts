import type {
  FileWorkspaceMutation,
  FileWorkspaceNode,
} from "../../../entities/file-workspace/model/fileWorkspace";
import type { DocumentFileSource } from "../../../entities/editor/model/editorDocument";
import {
  publishProjectFileMutation,
  subscribeProjectFileMutations,
} from "../../../entities/project/model/projectFileMutation";
import {
  getToolFolderWorkspaceKey,
  publishToolFolderFileMutation,
  subscribeToolFolderFileMutations,
  toFileWorkspaceMutation,
} from "../../../entities/tool/model/toolFolderFileMutation";
import type { FileWorkspaceApi } from "../../../entities/file-workspace/model/fileWorkspaceApi";
import { createProjectFileWorkspaceApi } from "../../../services/project/projectFileWorkspaceApi";
import { watchProjectFileEvents } from "../../../services/project/watchProjectFileEvents";
import type { ProjectFileWatchHandlers } from "../../../services/project/watchProjectFileEvents";
import { createToolFolderFileWorkspaceApi } from "../../../services/tools/toolFolderFileWorkspaceApi";

export type FileWorkspaceWatchHandlers = ProjectFileWatchHandlers;

export type DocumentFileSourceRuntime = {
  source: DocumentFileSource;
  getApi: () => FileWorkspaceApi;
  publishSavedNode?: (node: FileWorkspaceNode) => void;
  subscribeMutations?: (handler: (mutation: FileWorkspaceMutation) => void) => () => void;
  watchFileEvents?: (handlers: FileWorkspaceWatchHandlers) => () => void;
};

export function getProjectDocumentSourceKey(projectId: string) {
  return `project:${projectId}`;
}

export function createProjectDocumentSource(projectId: string): DocumentFileSourceRuntime {
  const sourceKey = getProjectDocumentSourceKey(projectId);
  return {
    source: {
      id: projectId,
      kind: "project",
      key: sourceKey,
    },
    getApi: () => createProjectFileWorkspaceApi(projectId),
    publishSavedNode: (node) => {
      publishProjectFileMutation({ projectId, node });
    },
    subscribeMutations: (handler) =>
      subscribeProjectFileMutations((mutation) => {
        if (mutation.projectId !== projectId) return;
        if (mutation.action === "delete") {
          handler({
            action: "delete",
            path: mutation.path,
            sourceId: mutation.sourceId,
            workspaceKey: sourceKey,
          });
          return;
        }
        if (mutation.action === "move") {
          handler({
            action: "move",
            previousPath: mutation.previousPath,
            node: mutation.node,
            sourceId: mutation.sourceId,
            workspaceKey: sourceKey,
          });
          return;
        }
        handler({
          action: "upsert",
          node: mutation.node,
          sourceId: mutation.sourceId,
          workspaceKey: sourceKey,
        });
      }),
    watchFileEvents: (handlers) => watchProjectFileEvents(projectId, handlers),
  };
}

export function createToolFolderDocumentSource(
  toolsetId: string,
  folderId: string,
  label?: string | null,
  projectId?: string | null,
): DocumentFileSourceRuntime {
  const sourceKey = getToolFolderWorkspaceKey(toolsetId, folderId);
  return {
    source: {
      id: folderId,
      kind: "tool-folder",
      key: sourceKey,
      label,
      projectId,
    },
    getApi: () => createToolFolderFileWorkspaceApi(toolsetId, folderId),
    publishSavedNode: (node) => {
      publishToolFolderFileMutation({
        action: "upsert",
        folderId,
        node,
        toolsetId,
      });
    },
    subscribeMutations: (handler) =>
      subscribeToolFolderFileMutations((mutation) => {
        if (mutation.toolsetId !== toolsetId || mutation.folderId !== folderId) return;
        handler(toFileWorkspaceMutation(mutation));
      }),
  };
}

export function isProjectFileSource(
  source: DocumentFileSource | null | undefined,
  projectId?: string | null,
) {
  if (!source || source.kind !== "project") {
    return false;
  }
  return projectId ? source.id === projectId : true;
}
