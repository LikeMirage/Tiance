import type { DocumentFileSource, DocumentTab } from "./editorDocument";

export type EditorWorkspaceFileReference = {
  fileSource: DocumentFileSource;
  kind: "file" | "folder";
  name: string;
  path: string;
};

export function getEditorDocumentPath(tab: Pick<DocumentTab, "displayPath" | "filePath" | "projectFilePath">) {
  return tab.filePath ?? tab.projectFilePath ?? tab.displayPath;
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
