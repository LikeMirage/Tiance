import type { ProjectFileNode } from "./project";

export function buildUserUploadsRootNode(): ProjectFileNode {
  return {
    id: ".Tiance/conversation_references",
    name: "conversation_references",
    path: ".Tiance/conversation_references",
    kind: "folder",
    has_children: true,
    mtime_ms: null,
    children: [],
  };
}

export function buildUserUploadImagesFolderNode(): ProjectFileNode {
  return {
    id: ".Tiance/conversation_references/images",
    name: "images",
    path: ".Tiance/conversation_references/images",
    kind: "folder",
    has_children: true,
    mtime_ms: null,
    children: [],
  };
}

export function buildUserUploadFilesFolderNode(): ProjectFileNode {
  return {
    id: ".Tiance/conversation_references/files",
    name: "files",
    path: ".Tiance/conversation_references/files",
    kind: "folder",
    has_children: true,
    mtime_ms: null,
    children: [],
  };
}
