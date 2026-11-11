import type { EditorExternalPathReferenceRequest } from "../../../entities/editor/model/editorReference";
import type { ProjectDragData } from "../../../entities/project/model/projectDragData";
import { normalizeAbsolutePath } from "./composerPathReferences";

export function buildComposerProjectReference(project: ProjectDragData): EditorExternalPathReferenceRequest | null {
  const path = normalizeAbsolutePath(project.root_path);
  if (!path) return null;
  return { kind: "folder", name: `${project.name}（Tiance 项目）`, path };
}

/** Menu selection and project drops enter the same existing folder-reference flow. */
export function referenceComposerProject(
  project: ProjectDragData,
  onReferenceExternalPath?: (reference: EditorExternalPathReferenceRequest) => void,
): boolean {
  const reference = buildComposerProjectReference(project);
  if (!reference || !onReferenceExternalPath) return false;
  onReferenceExternalPath(reference);
  return true;
}
