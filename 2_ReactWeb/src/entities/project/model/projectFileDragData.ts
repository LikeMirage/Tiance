import type { ProjectFileKind } from "./project";

export const PROJECT_FILE_DRAG_MIME_TYPE = "application/x-tiance-project-file";

export type ProjectFileDragData = {
  projectId: string;
  path: string;
  name: string;
  kind: ProjectFileKind;
};

export type ProjectFileReferenceRequest = ProjectFileDragData & {
  requestId: number;
};

export function serializeProjectFileDragData(data: ProjectFileDragData): string {
  return JSON.stringify(data);
}

export function parseProjectFileDragData(raw: string): ProjectFileDragData | null {
  if (!raw.trim()) return null;
  try {
    const payload = JSON.parse(raw) as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return null;
    }
    const record = payload as Record<string, unknown>;
    if (
      typeof record.projectId !== "string" ||
      typeof record.path !== "string" ||
      typeof record.name !== "string" ||
      (record.kind !== "file" && record.kind !== "folder")
    ) {
      return null;
    }
    return {
      projectId: record.projectId,
      path: record.path,
      name: record.name,
      kind: record.kind,
    };
  } catch {
    return null;
  }
}
