import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import type { ToolFolder, Toolset } from "../../../entities/tool/model/toolset";

export function toolsetsToProjectCategories(
  toolsets: readonly Toolset[],
): ProjectCategory[] {
  return toolsets.map((toolset, sortOrder) => ({
    category_id: toolset.category_id,
    name: toolset.name,
    category_kind: "tool",
    is_default: false,
    sort_order: sortOrder,
    created_at: toolset.created_at,
    updated_at: toolset.updated_at,
  }));
}

export function toolFoldersToProjects(
  folders: readonly ToolFolder[],
): Project[] {
  return folders.map((folder, sortOrder) => ({
    project_id: folder.project_id,
    name: folder.name,
    root_path: folder.root_path,
    category_id: folder.category_id,
    project_kind: "tool",
    is_default: false,
    is_managed: true,
    sort_order: sortOrder,
    created_at: folder.created_at,
    updated_at: folder.updated_at,
  }));
}
