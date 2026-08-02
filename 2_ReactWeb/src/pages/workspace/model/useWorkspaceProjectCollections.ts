import { useCallback, useEffect, useMemo, useRef } from "react";

import type {
  Project,
  ProjectCategory,
  ProjectKind,
} from "../../../entities/project/model/project";
import type { UseProjectCatalogResult } from "../../../features/project-catalog/model/useProjectCatalog";
import type { HoverSidebarSectionId } from "../../../widgets/hover-sidebar/model/sidebarSections";

export type WorkspaceProjectKind = Exclude<ProjectKind, "tool">;

type CollectionSelection = {
  categoryId: string | null;
  expandedProjectId: string | null;
  projectId: string | null;
  sessionId: string | null;
};

export type WorkspaceProjectCollection = {
  categories: ProjectCategory[];
  expandedProject: Project | null;
  projects: Project[];
  selectedCategoryId: string | null;
  selectedProject: Project | null;
  selectedSessionId: string | null;
};

const PROJECT_KINDS: readonly WorkspaceProjectKind[] = [
  "project",
  "knowledge",
  "experience",
  "role",
  "theme",
  "provider",
];

const SECTION_PROJECT_KINDS: Partial<Record<HoverSidebarSectionId, WorkspaceProjectKind>> = {
  experience: "experience",
  knowledge: "knowledge",
  models: "provider",
  overview: "project",
  roles: "role",
  themes: "theme",
};

export function getWorkspaceProjectKind(
  section: HoverSidebarSectionId,
): WorkspaceProjectKind | null {
  return SECTION_PROJECT_KINDS[section] ?? null;
}

export function useWorkspaceProjectCollections(catalog: UseProjectCatalogResult) {
  const selectionsRef = useRef<Record<WorkspaceProjectKind, CollectionSelection>>(
    createEmptySelections(),
  );

  const categoriesByKind = useMemo(
    () => groupCategoriesByKind(catalog.categories),
    [catalog.categories],
  );
  const projectsByKind = useMemo(
    () => groupProjectsByKind(catalog.items),
    [catalog.items],
  );

  useEffect(() => {
    const selectedCategory = catalog.selectedCategory;
    if (!selectedCategory || selectedCategory.category_kind === "tool") return;

    const kind = selectedCategory.category_kind;
    selectionsRef.current[kind] = {
      categoryId: selectedCategory.category_id,
      expandedProjectId: catalog.expandedProject?.project_kind === kind
        ? catalog.expandedProjectId
        : null,
      projectId: catalog.selectedProject?.project_kind === kind
        ? catalog.selectedProjectId
        : null,
      sessionId: catalog.selectedProject?.project_kind === kind
        ? catalog.selectedSessionId
        : null,
    };
  }, [
    catalog.expandedProject,
    catalog.expandedProjectId,
    catalog.selectedCategory,
    catalog.selectedProject,
    catalog.selectedProjectId,
    catalog.selectedSessionId,
  ]);

  const collections = useMemo(() => {
    const result = {} as Record<WorkspaceProjectKind, WorkspaceProjectCollection>;
    for (const kind of PROJECT_KINDS) {
      const categories = categoriesByKind[kind];
      const projects = projectsByKind[kind];
      const remembered = selectionsRef.current[kind];
      const isActiveKind = catalog.selectedCategory?.category_kind === kind;
      result[kind] = {
        categories,
        projects,
        selectedCategoryId: isActiveKind
          ? catalog.selectedCategoryId
          : remembered.categoryId ?? categories[0]?.category_id ?? null,
        selectedProject: catalog.selectedProject?.project_kind === kind
          ? catalog.selectedProject
          : findProject(projects, remembered.projectId),
        expandedProject: isActiveKind
          ? catalog.expandedProject?.project_kind === kind
            ? catalog.expandedProject
            : null
          : findProject(projects, remembered.expandedProjectId),
        selectedSessionId: catalog.selectedProject?.project_kind === kind
          ? catalog.selectedSessionId
          : remembered.sessionId,
      };
    }
    return result;
  }, [
    catalog.expandedProject,
    catalog.selectedCategory?.category_kind,
    catalog.selectedCategoryId,
    catalog.selectedProject,
    catalog.selectedSessionId,
    categoriesByKind,
    projectsByKind,
  ]);

  const activate = useCallback((kind: WorkspaceProjectKind) => {
    const collection = collections[kind];
    const remembered = selectionsRef.current[kind];
    const categoryId = collection.categories.some(
      (category) => category.category_id === remembered.categoryId,
    )
      ? remembered.categoryId
      : collection.categories[0]?.category_id ?? null;
    if (!categoryId) return;

    catalog.selectCategory(categoryId, {
      persistWorkspaceSelection: kind === "project",
    });
    const projectId = collection.projects.some(
      (project) => project.project_id === remembered.projectId && project.category_id === categoryId,
    )
      ? remembered.projectId
      : null;
    if (!projectId) return;
    if (remembered.expandedProjectId === projectId) {
      catalog.expandProject(projectId, remembered.sessionId);
      return;
    }
    catalog.selectProject(projectId, remembered.sessionId);
  }, [catalog.expandProject, catalog.selectCategory, catalog.selectProject, collections]);

  return { activate, collections };
}

function createEmptySelections(): Record<WorkspaceProjectKind, CollectionSelection> {
  const empty = (): CollectionSelection => ({
    categoryId: null,
    expandedProjectId: null,
    projectId: null,
    sessionId: null,
  });
  return {
    experience: empty(),
    knowledge: empty(),
    project: empty(),
    provider: empty(),
    role: empty(),
    theme: empty(),
  };
}

function groupCategoriesByKind(categories: readonly ProjectCategory[]) {
  const grouped = createEmptyGroups<ProjectCategory>();
  for (const category of categories) {
    if (category.category_kind !== "tool") grouped[category.category_kind].push(category);
  }
  return grouped;
}

function groupProjectsByKind(projects: readonly Project[]) {
  const grouped = createEmptyGroups<Project>();
  for (const project of projects) {
    if (project.project_kind !== "tool") grouped[project.project_kind].push(project);
  }
  return grouped;
}

function createEmptyGroups<T>(): Record<WorkspaceProjectKind, T[]> {
  return {
    experience: [],
    knowledge: [],
    project: [],
    provider: [],
    role: [],
    theme: [],
  };
}

function findProject(projects: readonly Project[], projectId: string | null) {
  return projects.find((project) => project.project_id === projectId) ?? null;
}
