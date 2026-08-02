import type { ProjectOverviewItem } from "../../../entities/project/model/project";
import type { ProjectOverviewLayoutMode } from "../../../entities/workspace/model/workspaceLayoutPreferences";

export type { ProjectOverviewLayoutMode } from "../../../entities/workspace/model/workspaceLayoutPreferences";

export type ProjectOverviewRollerPosition = "previous" | "center" | "next";

export type ProjectOverviewRollerItem = {
  item: ProjectOverviewItem;
  position: ProjectOverviewRollerPosition;
};

export const DEFAULT_PROJECT_OVERVIEW_LAYOUT: ProjectOverviewLayoutMode = "grid";

export function buildProjectOverviewRollerItems(
  projects: ProjectOverviewItem[],
  centerProjectId: string | null,
): ProjectOverviewRollerItem[] {
  if (projects.length === 0) return [];
  const centerIndex = Math.max(
    projects.findIndex((item) => item.project.project_id === centerProjectId),
    0,
  );
  const items: ProjectOverviewRollerItem[] = [
    { item: projects[centerIndex], position: "center" },
  ];
  if (projects.length === 1) return items;

  const previousIndex = (centerIndex - 1 + projects.length) % projects.length;
  items.unshift({ item: projects[previousIndex], position: "previous" });
  if (projects.length > 2) {
    const nextIndex = (centerIndex + 1) % projects.length;
    items.push({ item: projects[nextIndex], position: "next" });
  }
  return items;
}
