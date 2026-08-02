import type {
  Project,
  ProjectOverviewItem,
} from "../../../entities/project/model/project";

export function orderOverviewProjects(
  items: ProjectOverviewItem[],
  orderedProjects: Project[],
) {
  if (orderedProjects.length === 0) {
    return items;
  }
  const order = new Map(
    orderedProjects.map((project, index) => [project.project_id, index]),
  );
  return [...items].sort((a, b) => {
    const aOrder = order.get(a.project.project_id) ?? Number.MAX_SAFE_INTEGER;
    const bOrder = order.get(b.project.project_id) ?? Number.MAX_SAFE_INTEGER;
    if (aOrder !== bOrder) {
      return aOrder - bOrder;
    }
    return a.project.sort_order - b.project.sort_order;
  });
}
