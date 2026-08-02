import type { FileWorkspaceApi } from "../../entities/file-workspace/model/fileWorkspaceApi";
import type {
  FileWorkspaceContentResponse,
  FileWorkspaceCopyRequest,
  FileWorkspaceCreateRequest,
  FileWorkspaceMoveRequest,
  FileWorkspaceNode,
  FileWorkspaceOpenExternalRequest,
  FileWorkspaceOpenExternalResponse,
  FileWorkspaceRevealRequest,
  FileWorkspaceTreeResponse,
} from "../../entities/file-workspace/model/fileWorkspace";
import { getToolFolderWorkspaceKey } from "../../entities/tool/model/toolFolderFileMutation";
import { isAbortError } from "../http/httpErrors";
import { fetchJson, fetchNoContent } from "../http/httpClient";

const SAVE_TOOL_FILE_TIMEOUT_MS = 60000;

export function createToolFolderFileWorkspaceApi(
  toolsetId: string,
  folderId: string,
): FileWorkspaceApi {
  return {
    copyEntry: (payload) => copyToolFolderFile(toolsetId, folderId, payload),
    createEntry: (payload) => createToolFolderFile(toolsetId, folderId, payload),
    deleteEntry: (path) => deleteToolFolderFile(toolsetId, folderId, path),
    listTree: (options, init) => getToolFolderFiles(toolsetId, folderId, options, init),
    moveEntry: (payload) => moveToolFolderFile(toolsetId, folderId, payload),
    readTextFile: async (path) => {
      const response = await getToolFolderFileContent(toolsetId, folderId, path);
      return {
        path: response.path,
        content: response.content,
        mtime_ms: response.mtime_ms,
      };
    },
    renameEntry: (path, name) => renameToolFolderFile(toolsetId, folderId, path, name),
    revealEntry: (payload) => revealToolFolderFile(toolsetId, folderId, payload),
    saveTextFile: (path, content, options) =>
      saveToolFolderFileContent(toolsetId, folderId, path, content, options),
    workspaceKey: getToolFolderWorkspaceKey(toolsetId, folderId),
  };
}

function getToolFolderFiles(
  toolsetId: string,
  folderId: string,
  options: { parentPath?: string | null; query?: string } = {},
  init?: Pick<RequestInit, "signal">,
) {
  const search = new URLSearchParams();
  if (options.query?.trim()) search.set("query", options.query.trim());
  if (options.parentPath?.trim()) search.set("parent_path", options.parentPath.trim());
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return fetchJson<FileWorkspaceTreeResponse>(
    `${toolFolderFilesPath(toolsetId, folderId)}${suffix}`,
    {
      signal: init?.signal,
    },
  );
}

function createToolFolderFile(
  toolsetId: string,
  folderId: string,
  payload: FileWorkspaceCreateRequest,
) {
  return fetchJson<FileWorkspaceNode>(
    toolFolderFilesPath(toolsetId, folderId),
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

function renameToolFolderFile(
  toolsetId: string,
  folderId: string,
  path: string,
  name: string,
) {
  return fetchJson<FileWorkspaceNode>(
    toolFolderFilesPath(toolsetId, folderId),
    {
      method: "PATCH",
      body: JSON.stringify({ path, name }),
    },
  );
}

function deleteToolFolderFile(toolsetId: string, folderId: string, path: string) {
  return fetchNoContent(
    `${toolFolderFilesPath(toolsetId, folderId)}?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
}

function moveToolFolderFile(
  toolsetId: string,
  folderId: string,
  payload: FileWorkspaceMoveRequest,
) {
  return fetchJson<FileWorkspaceNode>(
    `${toolFolderFilesPath(toolsetId, folderId)}/move`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

function copyToolFolderFile(
  toolsetId: string,
  folderId: string,
  payload: FileWorkspaceCopyRequest,
) {
  return fetchJson<FileWorkspaceNode>(
    `${toolFolderFilesPath(toolsetId, folderId)}/copy`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function revealToolFolderFile(
  toolsetId: string,
  folderId: string,
  payload: FileWorkspaceRevealRequest,
) {
  return fetchNoContent(
    `${toolFolderFilesPath(toolsetId, folderId)}/reveal`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function openToolFolderFileExternal(
  toolsetId: string,
  folderId: string,
  payload: FileWorkspaceOpenExternalRequest,
) {
  return fetchJson<FileWorkspaceOpenExternalResponse & { category_id: string; project_id: string }>(
    `${toolFolderFilesPath(toolsetId, folderId)}/open-external`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

function getToolFolderFileContent(toolsetId: string, folderId: string, path: string) {
  return fetchJson<FileWorkspaceContentResponse>(
    `${toolFolderFilesPath(toolsetId, folderId)}/content?path=${encodeURIComponent(path)}`,
  );
}

function saveToolFolderFileContent(
  toolsetId: string,
  folderId: string,
  path: string,
  content: string,
  options?: Pick<RequestInit, "signal"> & { expectedMtimeMs?: number | null },
) {
  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = window.setTimeout(() => {
    didTimeout = true;
    controller.abort();
  }, SAVE_TOOL_FILE_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  if (options?.signal?.aborted) {
    controller.abort();
  } else {
    options?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const payload: { content: string; expected_mtime_ms?: number } = { content };
  if (options?.expectedMtimeMs != null) {
    payload.expected_mtime_ms = options.expectedMtimeMs;
  }

  return fetchJson<FileWorkspaceNode>(
    `${toolFolderFilesPath(toolsetId, folderId)}/content?path=${encodeURIComponent(path)}`,
    { method: "PUT", body: JSON.stringify(payload), signal: controller.signal },
  ).catch((err) => {
    if (isAbortError(err) && didTimeout) {
      throw new Error("文件保存超时，请稍后重试。");
    }
    throw err;
  }).finally(() => {
    window.clearTimeout(timeoutId);
    options?.signal?.removeEventListener("abort", abortFromCaller);
  });
}

function toolFolderFilesPath(toolsetId: string, folderId: string) {
  return `/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/files`;
}
