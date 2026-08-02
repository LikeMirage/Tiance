import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import { HttpRequestError } from "../../../services/http/httpClient";
import { saveProjectOrder } from "../../../services/project/saveProjectOrder";

export type LoadState = "loading" | "ready" | "error";

export type ProjectImportConflict = {
  categoryId: string;
  categoryName: string;
  projectId: string;
  projectName: string;
  rootPath: string;
};

export function applyProjectOrder(items: Project[], orderedIds: string[]): Project[] {
  const idToItem = new Map(items.map((item) => [item.project_id, item]));
  const ordered: Project[] = [];
  for (const id of orderedIds) {
    const item = idToItem.get(id);
    if (item) {
      ordered.push(item);
      idToItem.delete(id);
    }
  }
  // 追加不在排序列表中的项目
  for (const remaining of idToItem.values()) {
    ordered.push(remaining);
  }
  return ordered;
}

export function persistProjectOrderSilently(projects: Project[]) {
  saveProjectOrder(projects.map((p) => p.project_id)).catch(() => undefined);
}

export function getCategoryProjects(
  items: readonly Project[],
  categoryId: string | null,
): Project[] {
  if (!categoryId) return [...items];
  return items.filter((item) => item.category_id === categoryId);
}

export function resolveSelectedCategoryId(
  categories: readonly ProjectCategory[],
  requestedCategoryId: string | null,
) {
  if (
    requestedCategoryId &&
    categories.some((category) => category.category_id === requestedCategoryId)
  ) {
    return requestedCategoryId;
  }
  return (
    categories.find((category) => category.is_default)?.category_id ??
    categories[0]?.category_id ??
    null
  );
}

export function resolveSelectedProjectId(
  items: readonly Project[],
  categoryId: string | null,
  requestedProjectId: string | null,
) {
  const categoryItems = categoryId
    ? items.filter((item) => item.category_id === categoryId)
    : items;
  if (
    requestedProjectId &&
    categoryItems.some((item) => item.project_id === requestedProjectId)
  ) {
    return requestedProjectId;
  }
  return (
    categoryItems.find((item) => item.is_default)?.project_id ??
    categoryItems[0]?.project_id ??
    null
  );
}

export function parseProjectImportConflict(error: unknown): ProjectImportConflict | null {
  if (!(error instanceof HttpRequestError) || error.status !== 409) {
    return null;
  }

  const details = error.details;
  if (!isProjectImportConflictDetails(details)) {
    return null;
  }

  return {
    categoryId: details.category_id,
    categoryName: details.category_name,
    projectId: details.project_id,
    projectName: details.project_name,
    rootPath: details.root_path,
  };
}

function isProjectImportConflictDetails(value: unknown): value is {
  category_id: string;
  category_name: string;
  kind: "project_already_imported";
  project_id: string;
  project_name: string;
  root_path: string;
} {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  return (
    payload.kind === "project_already_imported" &&
    typeof payload.category_id === "string" &&
    typeof payload.category_name === "string" &&
    typeof payload.project_id === "string" &&
    typeof payload.project_name === "string" &&
    typeof payload.root_path === "string"
  );
}
