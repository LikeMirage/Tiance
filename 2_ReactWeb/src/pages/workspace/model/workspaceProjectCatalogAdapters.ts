import type {
  Project,
  ProjectCategory,
  ProjectKind,
} from "../../../entities/project/model/project";
import type {
  UseProjectCatalogResult,
  ProjectImportConflict,
} from "../../../features/project-catalog/model/useProjectCatalog";
type CatalogProjectKind = Exclude<ProjectKind, "tool">;

type HoverCatalogInput = {
  catalog: UseProjectCatalogResult;
  categories: ProjectCategory[];
  createCategory: () => Promise<void>;
  deleteCategory?: (categoryId: string) => Promise<void>;
  kind: CatalogProjectKind;
  selectedCategoryId: string | null;
  selectCategory: UseProjectCatalogResult["selectCategory"];
};

export function buildHoverProjectCatalog({
  catalog,
  categories,
  createCategory,
  deleteCategory,
  kind,
  selectedCategoryId,
  selectCategory,
}: HoverCatalogInput) {
  const pendingCategory = catalog.categories.find(
    (category) => category.category_id === catalog.pendingRenameCategoryId,
  );
  return {
    categories,
    clearPendingRenameCategory: catalog.clearPendingRenameCategory,
    createProjectCategory: createCategory,
    deleteProjectCategory: deleteCategory ?? catalog.deleteProjectCategory,
    error: catalog.error,
    isCreatingProjectCategory: catalog.isCreatingProjectCategory,
    pendingRenameCategoryId:
      pendingCategory?.category_kind === kind ? catalog.pendingRenameCategoryId : null,
    renameProjectCategory: catalog.renameProjectCategory,
    selectedCategoryId,
    selectCategory,
    state: catalog.state,
  };
}

export function buildHoverThemeCatalog(
  input: HoverCatalogInput & { items: Project[] },
) {
  return {
    ...buildHoverProjectCatalog(input),
    items: input.items,
  };
}

type SidePanelCatalogInput = {
  catalog: UseProjectCatalogResult;
  categories: ProjectCategory[];
  collapseProject: () => void;
  createProject: () => Promise<void>;
  duplicateImportConflict: ProjectImportConflict | null;
  expandProject: (projectId: string) => boolean | void | Promise<boolean | void>;
  expandedProject: Project | null;
  items: Project[];
  jumpToImportConflictProject: () => void;
  kind: CatalogProjectKind;
  prepareProject: (projectId: string) => void;
  selectedCategoryId: string | null;
  selectedProject: Project | null;
  selectProject: (projectId: string) => boolean | void | Promise<boolean | void>;
};

export function buildSidePanelProjectCatalog({
  catalog,
  categories,
  collapseProject,
  createProject,
  duplicateImportConflict,
  expandProject,
  expandedProject,
  items,
  jumpToImportConflictProject,
  kind,
  prepareProject,
  selectedCategoryId,
  selectedProject,
  selectProject,
}: SidePanelCatalogInput) {
  const pendingProject = catalog.items.find(
    (project) => project.project_id === catalog.pendingRenameProjectId,
  );
  return {
    categories,
    clearPendingRenameProject: catalog.clearPendingRenameProject,
    collapseProject,
    createProject,
    createProjectFromFolder: catalog.createProjectFromFolder,
    createProjectsFromFolders: catalog.createProjectsFromFolders,
    deleteProject: catalog.deleteProject,
    dismissImportConflict: catalog.dismissImportConflict,
    duplicateImportConflict,
    error: catalog.error,
    expandProject,
    expandedProject,
    expandedProjectId: expandedProject?.project_id ?? null,
    getReorderedProjectIds: catalog.getReorderedProjectIds,
    isCreatingProject: catalog.isCreatingProject,
    items,
    jumpToImportConflictProject,
    moveProjectToCategory: catalog.moveProjectToCategory,
    pendingRenameProjectId:
      pendingProject?.project_kind === kind ? catalog.pendingRenameProjectId : null,
    pinProjectToCategoryTop: catalog.pinProjectToCategoryTop,
    persistProjectOrder: catalog.persistProjectOrder,
    prepareProject,
    previewProjectOrder: catalog.previewProjectOrder,
    revealProject: catalog.revealProject,
    reload: catalog.reload,
    renameProject: catalog.renameProject,
    selectProject,
    selectedCategory:
      categories.find((category) => category.category_id === selectedCategoryId) ?? null,
    selectedCategoryId,
    selectedCategoryProjects: items.filter(
      (project) => project.category_id === selectedCategoryId,
    ),
    selectedProjectId: selectedProject?.project_id ?? null,
    state: catalog.state,
  };
}
