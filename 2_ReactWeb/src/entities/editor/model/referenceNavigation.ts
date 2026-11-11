import type { EditorFileReference, EditorReferenceViewerPayload } from "./editorReference";
import type { DocumentRevealTarget } from "./documentReveal";

/** Image excerpts point at their original document, never their saved screenshot. */
export function referenceOriginalFile(payload: EditorReferenceViewerPayload): EditorFileReference {
  if (payload.kind === "file") return payload.reference;
  const ref = payload.reference;
  const path = payload.kind === "image" ? payload.reference.sourceFilePath : ref.filePath;
  return {
    id: ref.id, kind: "file", projectId: ref.projectId,
    filePath: path,
    displayPath: payload.kind === "image" ? payload.reference.sourceDisplayPath : ref.displayPath,
    fileName: payload.kind === "image" ? payload.reference.sourceFileName : ref.fileName,
    source: /^(?:[a-z]:[\\/]|\/|\\\\)/i.test(path) ? "external_path" : "project_file",
  };
}

export function referenceRevealTarget(payload: EditorReferenceViewerPayload): DocumentRevealTarget | null {
  if (payload.kind === "file") return null;
  if (payload.kind === "text") {
    if (payload.reference.source === "pdf") {
      const page = payload.reference.pageNumber;
      return page && Number.isSafeInteger(page) && page > 0 ? { type: "pdf_page", page } : null;
    }
    return { type: "reference_text", reference: payload.reference };
  }
  if (payload.reference.source === "pdf_page") {
    const page = payload.reference.pageNumber;
    return page && Number.isSafeInteger(page) && page > 0 ? { type: "pdf_page", page } : null;
  }
  return { type: "reference_image", reference: payload.reference };
}
