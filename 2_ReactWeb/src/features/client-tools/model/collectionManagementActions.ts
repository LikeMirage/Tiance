import type { Project, ProjectKind } from "../../../entities/project/model/project";
import { getProjects } from "../../../services/project/getProjects";
import { getProjectCategories } from "../../../services/project/getProjectCategories";
import { createProjectCategory } from "../../../services/project/createProjectCategory";
import { deleteProject } from "../../../services/project/deleteProject";
import { fetchJson } from "../../../services/http/httpClient";
import { dispatchProjectCatalogChanged } from "../../../entities/project/model/projectCatalogEvents";
import { publishToolCatalogChange } from "../../../entities/tool/model/toolCatalogEvents";
import { readRequiredString } from "./conversationClientToolValues";

export function notifyCollectionChanged(kind: ProjectKind) {
  dispatchProjectCatalogChanged();
  if (kind === "tool") publishToolCatalogChange({ kind: "toolsets" });
}

export async function requireCollectionProject(kind: ProjectKind, projectId: string) {
  const { items } = await getProjects();
  const project = items.find((item) => item.project_id === projectId && item.project_kind === kind);
  if (!project) throw new Error(`项目未登记在 ${kind} 集中：${projectId}`);
  return project;
}

export async function collectionManagementAction(
  kind: "tool" | "role", action: string, args: Record<string, unknown>,
  callerProjectId: string, executingToolProjectId: string,
): Promise<Record<string, unknown> | undefined> {
  if (action === "list_categories") {
    const { items } = await getProjectCategories();
    return { action, categories: items.filter((item) => item.category_kind === kind) };
  }
  if (action === "create_category") {
    const category = await createProjectCategory(readRequiredString(args, "name"), kind);
    notifyCollectionChanged(kind);
    return { action, category };
  }
  if (action === "list") {
    const { items } = await getProjects();
    return { action, projects: items.filter((item) => item.project_kind === kind
      && (args.category_id === undefined || item.category_id === args.category_id)) };
  }
  if (!["delete", "rename", "move"].includes(action)) return undefined;
  const projectId = readRequiredString(args, "project_id");
  const project = await requireCollectionProject(kind, projectId);
  if (action === "delete") {
    if (args.confirm !== true) throw new Error("删除需要 confirm=true，请先核对目标项目。");
    if (projectId === callerProjectId || projectId === executingToolProjectId) {
      throw new Error("不能删除本次调用所在项目或正在执行的管理工具。");
    }
    await deleteProject(projectId);
    notifyCollectionChanged(kind);
    return { action, project, deleted: true };
  }
  const updated = await fetchJson<Project>(`/api/projects/${encodeURIComponent(projectId)}${action === "move" ? "/category" : ""}`, {
    method: "PATCH", body: JSON.stringify(action === "move"
      ? { category_id: readRequiredString(args, "category_id") }
      : { name: readRequiredString(args, "name") }),
  });
  notifyCollectionChanged(kind);
  return { action, project: updated };
}
