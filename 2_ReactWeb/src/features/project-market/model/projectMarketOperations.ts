import type { ProjectCategory } from "../../../entities/project/model/project";
import type {
  ProjectMarketFilters,
  ProjectMarketInstallPhase,
  ProjectMarketProject,
  ProjectMarketScope,
} from "./projectMarket";

const ACTIVE_PHASES: readonly ProjectMarketInstallPhase[] = [
  "queued",
  "downloading",
  "extracting",
  "importing",
];

export function filterProjectMarketProjects(
  projects: readonly ProjectMarketProject[],
  filters: ProjectMarketFilters,
  query: string,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return projects.filter((project) => {
    if (filters.authors.length && !filters.authors.includes(project.author)) return false;
    if (filters.statuses.length && !filters.statuses.includes(project.installationStatus)) {
      return false;
    }
    if (filters.tags.length && !project.tags.some((tag) => filters.tags.includes(tag))) {
      return false;
    }
    if (!normalizedQuery) return true;
    return [project.name, project.id, project.author, project.summary, ...project.tags]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function listProjectMarketAuthors(projects: readonly ProjectMarketProject[]) {
  return [...new Set(projects.map((project) => project.author))].sort();
}

export function listProjectMarketTags(projects: readonly ProjectMarketProject[]) {
  return [...new Set(projects.flatMap((project) => project.tags))].sort();
}

export function filterProjectMarketCategories(
  categories: readonly ProjectCategory[],
  scope: ProjectMarketScope,
) {
  return categories.filter((category) => category.category_kind === scope);
}

export function isProjectMarketInstallActive(phase: ProjectMarketInstallPhase | undefined) {
  return phase !== undefined && ACTIVE_PHASES.includes(phase);
}
