import type { FileWorkspaceContentResponse, FileWorkspaceNode } from "../../entities/file-workspace/model/fileWorkspace";
import type { EditorFileReference } from "../../entities/editor/model/editorReference";
import type { ReferenceOpenResolution } from "../../entities/editor/model/editorReference";
import { fetchJson } from "../http/httpClient";

export type ResolvedFileReference = {
  kind: "project" | "local";
  root: string;
  path: string;
  name: string;
  mtime_ms: number;
};

export function resolveFileReference(reference: EditorFileReference, ownerProjectId: string,
  sessionId: string | null, signal?: AbortSignal) {
  return fetchJson<ResolvedFileReference | Extract<ReferenceOpenResolution, { kind: "folder" }>>("/api/editor/file-references/resolve", {
    method: "POST", signal,
    body: JSON.stringify({ path: reference.filePath, source: reference.source, kind: reference.kind,
      project_id: reference.projectId ?? ownerProjectId, session_id: sessionId,
      owner_project_id: ownerProjectId }),
  });
}

export function readLocalEditorText(path: string, init?: Pick<RequestInit, "signal">) {
  return fetchJson<FileWorkspaceContentResponse>(localFileEndpoint(path, "content"), init);
}

export function saveLocalEditorText(path: string, content: string,
  options?: Pick<RequestInit, "signal"> & { expectedMtimeMs?: number | null }) {
  return fetchJson<FileWorkspaceNode>(localFileEndpoint(path, "content"), {
    method: "PUT", signal: options?.signal,
    body: JSON.stringify({ content, expected_mtime_ms: options?.expectedMtimeMs }),
  });
}

export function readLocalEditorMetadata(path: string) {
  return fetchJson<{ mtime_ms: number }>(localFileEndpoint(path, "metadata"));
}

export function localFileEndpoint(path: string, operation: string) {
  return `/api/editor/local/files/${operation}?path=${encodeURIComponent(path)}`;
}
