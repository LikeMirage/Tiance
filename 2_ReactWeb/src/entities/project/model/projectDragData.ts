import type { Project } from "./project";

export const PROJECT_DRAG_MIME_TYPE = "application/x-tiance-project";
export type ProjectDragData = Pick<Project, "project_id" | "name" | "root_path">;

export function serializeProjectDragData(project: ProjectDragData): string {
  return JSON.stringify({ project_id: project.project_id, name: project.name, root_path: project.root_path });
}

export function parseProjectDragData(raw: string): ProjectDragData | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const project = value as Record<string, unknown>;
    if (typeof project.project_id !== "string" || !project.project_id.trim()
      || typeof project.name !== "string" || !project.name.trim()
      || typeof project.root_path !== "string" || !project.root_path.trim()) return null;
    return { project_id: project.project_id, name: project.name, root_path: project.root_path };
  } catch {
    return null;
  }
}
