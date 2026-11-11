import { documentDisplayPath } from "./documentFilePath";
import type { DocumentFileSource, DocumentTab } from "./editorDocument";

export type EditorWorkspaceFileReference = {
  fileSource: DocumentFileSource;
  kind: "file" | "folder";
  name: string;
  path: string;
};

export function getEditorDocumentPath(tab: Pick<DocumentTab, "displayPath" | "filePath" | "projectFilePath"> & Partial<Pick<DocumentTab, "fileSource">>) {
  const path = tab.filePath ?? tab.projectFilePath;
  return path ? documentDisplayPath(tab.fileSource ?? null, path) : tab.displayPath;
}

export function createEditorWorkspaceFileReference(
  tab: DocumentTab,
  kind: EditorWorkspaceFileReference["kind"] = "file",
): EditorWorkspaceFileReference | null {
  if (!tab.fileSource) return null;
  const path = getEditorDocumentPath(tab);
  if (!path) return null;
  return {
    fileSource: tab.fileSource,
    kind,
    name: tab.title,
    path,
  };
}
