import type { FileWorkspaceApi } from "../../entities/file-workspace/model/fileWorkspaceApi";
import { copyProjectFile } from "./copyProjectFile";
import { createProjectFile } from "./createProjectFile";
import { deleteProjectFile } from "./deleteProjectFile";
import { getProjectFileContent } from "./getProjectFileContent";
import { getProjectFiles } from "./getProjectFiles";
import { moveProjectFile } from "./moveProjectFile";
import { renameProjectFile } from "./renameProjectFile";
import { revealProjectFile } from "./revealProjectFile";
import { saveProjectFileContent } from "./saveProjectFileContent";

export function createProjectFileWorkspaceApi(projectId: string): FileWorkspaceApi {
  return {
    copyEntry: (payload) => copyProjectFile(projectId, payload),
    createEntry: (payload) => createProjectFile(projectId, payload),
    deleteEntry: (path) => deleteProjectFile(projectId, path),
    listTree: (options, init) => getProjectFiles(projectId, options, init),
    moveEntry: (payload) => moveProjectFile(projectId, payload),
    readTextFile: async (path) => {
      const response = await getProjectFileContent(projectId, path);
      return {
        path: response.path,
        content: response.content,
        mtime_ms: response.mtime_ms,
      };
    },
    renameEntry: (path, name) => renameProjectFile(projectId, path, name),
    revealEntry: (payload) => revealProjectFile(projectId, payload),
    saveTextFile: (path, content, options) =>
      saveProjectFileContent(projectId, path, content, options),
    workspaceKey: `project:${projectId}`,
  };
}
