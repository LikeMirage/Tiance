import type {
  DocumentFileSource,
  DocumentTab,
} from "../../../entities/editor/model/editorDocument";
import { parseToolFolderWorkspaceKey } from "../../../entities/tool/model/toolFolderFileMutation";
import { env } from "../../../shared/config/env";

export function resolveDocumentAssetUrl(tab: DocumentTab | null) {
  if (!tab?.fileSource || !tab.filePath) {
    return null;
  }
  const path = normalizeWorkspaceAssetPath(tab.filePath);
  if (!path) {
    return null;
  }
  return createWorkspaceAssetUrl(tab.fileSource, path, tab.assetVersion ?? tab.mtimeMs);
}

export function createWorkspaceAssetUrl(source: DocumentFileSource, path: string, version: number | null = null) {
  const normalizedPath = normalizeWorkspaceAssetPath(path);
  if (!normalizedPath) {
    return null;
  }

  if (source.kind === "project") {
    return withAssetVersion(projectAssetUrl(source.id, normalizedPath), version);
  }

  if (source.kind === "tool-folder") {
    const folder = parseToolFolderWorkspaceKey(source.key);
    return folder
      ? withAssetVersion(toolFolderAssetUrl(folder.toolsetId, folder.folderId, normalizedPath), version)
      : null;
  }

  return null;
}

export function normalizeWorkspaceAssetPath(path: string) {
  return path.replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

function projectAssetUrl(projectId: string, path: string) {
  return `${env.apiBaseUrl}/api/projects/${encodeURIComponent(projectId)}/files/asset?path=${encodeURIComponent(path)}`;
}

function toolFolderAssetUrl(toolsetId: string, folderId: string, path: string) {
  return `${env.apiBaseUrl}/api/tools/categories/${encodeURIComponent(toolsetId)}/projects/${encodeURIComponent(folderId)}/files/asset?path=${encodeURIComponent(path)}`;
}

function withAssetVersion(url: string, version: number | null) {
  return typeof version === "number" ? `${url}&v=${encodeURIComponent(String(version))}` : url;
}
