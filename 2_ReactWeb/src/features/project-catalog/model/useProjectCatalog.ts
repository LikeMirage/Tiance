import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  Project,
  ProjectCategory,
  ProjectKind,
} from "../../../entities/project/model/project";
import {
  dispatchProjectCatalogChanged,
  listenProjectCatalogChanged,
} from "../../../entities/project/model/projectCatalogEvents";
import { createProjectCategory as createProjectCategoryRequest } from "../../../services/project/createProjectCategory";
import { createProject as createProjectRequest } from "../../../services/project/createProject";
import { createRoleProject as createRoleProjectRequest } from "../../../services/project/createRoleProject";
import { deleteProjectCategory as deleteProjectCategoryRequest } from "../../../services/project/deleteProjectCategory";
import { deleteProject as deleteProjectRequest } from "../../../services/project/deleteProject";
import { getProjectCategories } from "../../../services/project/getProjectCategories";
import { getProjectOrder } from "../../../services/project/getProjectOrder";
import { getProjects } from "../../../services/project/getProjects";
import { moveProjectToCategory as moveProjectToCategoryRequest } from "../../../services/project/moveProjectToCategory";
import { revealProjectFile as revealProjectFileRequest } from "../../../services/project/revealProjectFile";
import { renameProjectCategory as renameProjectCategoryRequest } from "../../../services/project/renameProjectCategory";
import { renameProject as renameProjectRequest } from "../../../services/project/renameProject";
import { saveProjectOrder } from "../../../services/project/saveProjectOrder";
import { watchProjectWorkspaceEvents } from "../../../services/project/watchProjectWorkspaceEvents";
import {
  getWorkspaceLastOpened,
  saveWorkspaceLastOpened,
} from "../../../services/workspace/workspaceLastOpened";
import {
  applyProjectOrder,
  getCategoryProjects,
  parseProjectImportConflict,
  persistProjectOrderSilently,
  resolveSelectedCategoryId,
  type LoadState,
  type ProjectImportConflict,
} from "./projectCatalogHelpers";
import {
  runProjectFolderImportBatch,
  type ProjectFolderImportBatchResult,
} from "./projectFolderImportBatch";
import { useProjectCatalogSelection, type ProjectCatalogSelection } from "./useProjectCatalogSelection";

export type { ProjectImportConflict } from "./projectCatalogHelpers";

export type ProjectFolderImportSummary = {
  conflictCount: number;
  createdCount: number;
  failedCount: number;
};

export type UseProjectCatalogResult = {
  categories: ProjectCategory[];
  collapseProject: () => void;
  clearPendingRenameCategory: () => void;
  confirmSessionSelection: (projectId: string, sessionId: string | null) => void;
  createProject: () => Promise<void>;
  createKnowledgeProject: () => Promise<void>;
  createExperienceProject: () => Promise<void>;
  createRoleProject: () => Promise<void>;
  createThemeProject: () => Promise<void>;
  createProjectCategory: () => Promise<void>;
  createKnowledgeProjectCategory: () => Promise<void>;
  createExperienceProjectCategory: () => Promise<void>;
  createRoleProjectCategory: () => Promise<void>;
  createProviderProjectCategory: () => Promise<void>;
  createThemeProjectCategory: () => Promise<void>;
  createProjectFromFolder: (rootPath: string) => Promise<void>;
  createProjectsFromFolders: (rootPaths: string[]) => Promise<ProjectFolderImportSummary>;
  deleteProjectCategory: (categoryId: string) => Promise<void>;
  deleteProject: (projectId: string, options?: { deleteFiles?: boolean }) => Promise<void>;
  deletingProjectId: string | null;
  dismissImportConflict: () => void;
  duplicateImportConflict: ProjectImportConflict | null;
  error: string | null;
  expandedProject: Project | null;
  expandedProjectId: string | null;
  expandProject: (projectId: string, sessionId?: string | null) => void;
  getReorderedProjectIds: (
    activeId: string,
    targetId: string,
    position: "before" | "after",
  ) => string[];
  isCreatingProject: boolean;
  isCreatingProjectCategory: boolean;
  items: Project[];
  jumpToImportConflictProject: () => void;
  moveProjectToCategory: (projectId: string, categoryId: string) => Promise<void>;
  pendingRenameCategoryId: string | null;
  pendingRenameProjectId: string | null;
  pinProjectToCategoryTop: (projectId: string) => Promise<void>;
  persistProjectOrder: (projectIds: string[]) => Promise<void>;
  previewProjectOrder: (projectIds: string[]) => void;
  clearPendingRenameProject: () => void;
  revealProject: (projectId: string) => Promise<void>;
  reload: () => void;
  renameProjectCategory: (categoryId: string, name: string) => Promise<void>;
  renameProject: (projectId: string, name: string) => Promise<void>;
  selectedCategory: ProjectCategory | null;
  selectedCategoryId: string | null;
  selectedCategoryProjects: Project[];
  selectedProject: Project | null;
  selectedProjectId: string | null;
  selectedSessionId: string | null;
  selectCategory: (
    categoryId: string,
    options?: { persistWorkspaceSelection?: boolean },
  ) => void;
  selectProject: (projectId: string, sessionId?: string | null) => void;
  state: LoadState;
};

export function useProjectCatalog(): UseProjectCatalogResult {
  const itemsRef = useRef<Project[]>([]);
  const categoriesRef = useRef<ProjectCategory[]>([]);
  const {
    currentRef: selectionRef,
    getCategorySelection,
    restoreSavedSelections,
    select: applySelection,
    selection: {
      categoryId: selectedCategoryId,
      projectId: selectedProjectId,
      sessionId: selectedSessionId,
    },
  } = useProjectCatalogSelection();
  const hasAppliedInitialWorkspaceStateRef = useRef(false);
  const hasLoadedCatalogRef = useRef(false);
  const [items, setItems] = useState<Project[]>([]);
  const [categories, setCategories] = useState<ProjectCategory[]>([]);
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [isCreatingProjectCategory, setIsCreatingProjectCategory] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [duplicateImportConflict, setDuplicateImportConflict] =
    useState<ProjectImportConflict | null>(null);
  const [pendingRenameCategoryId, setPendingRenameCategoryId] = useState<string | null>(null);
  const [pendingRenameProjectId, setPendingRenameProjectId] = useState<string | null>(null);
  const clearPendingRenameCategory = useCallback(() => {
    setPendingRenameCategoryId(null);
  }, []);
  const clearPendingRenameProject = useCallback(() => {
    setPendingRenameProjectId(null);
  }, []);

  const selectNavigation = useCallback((next: ProjectCatalogSelection, persist = true) => {
    applySelection(next);
    if (persist && next.categoryId) {
      void saveWorkspaceLastOpened({
        category_id: next.categoryId,
        project_id: next.projectId,
      }).catch(() => undefined);
    }
  }, [applySelection]);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    categoriesRef.current = categories;
  }, [categories]);

  useEffect(
    () => listenProjectCatalogChanged(
      () => setRequestKey((current) => current + 1),
    ),
    [],
  );

  useEffect(
    () => watchProjectWorkspaceEvents(() => dispatchProjectCatalogChanged()),
    [],
  );

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (!hasLoadedCatalogRef.current) {
        setState("loading");
      }
      setError(null);

      try {
        const [response, categoryResponse, orderResponse] = await Promise.all([
          getProjects(),
          getProjectCategories(),
          getProjectOrder().catch(() => null),
        ]);
        if (cancelled) return;

        let ordered = response.items;
        if (orderResponse?.project_ids?.length) {
          ordered = applyProjectOrder(response.items, orderResponse.project_ids);
        }

        const loadedCategories = categoryResponse.items;
        const workspaceState = hasAppliedInitialWorkspaceStateRef.current
          ? null
          : await getWorkspaceLastOpened().catch(() => null);
        if (cancelled) return;

        // Only initial hydration reads saved navigation. Catalog refreshes
        // validate the local choice; they do not reset category memories.
        restoreSavedSelections(workspaceState);
        const requestedCategoryId =
          selectionRef.current.categoryId ?? workspaceState?.category_id ?? null;
        const requestedCategory = loadedCategories.find(
          (category) => category.category_id === requestedCategoryId,
        );
        const requestedCategoryKind = requestedCategory?.category_kind ?? "project";
        const matchingCategories = loadedCategories.filter(
          (category) => category.category_kind === requestedCategoryKind,
        );
        const nextCategoryId = resolveSelectedCategoryId(
          matchingCategories,
          requestedCategoryId,
        );
        hasAppliedInitialWorkspaceStateRef.current = true;
        itemsRef.current = ordered;
        categoriesRef.current = loadedCategories;
        setItems(ordered);
        setCategories(loadedCategories);
        const next = getCategorySelection(ordered, nextCategoryId);
        const current = selectionRef.current;
        applySelection({
          ...next,
          sessionId: next.projectId && current.categoryId === next.categoryId && current.projectId === next.projectId
            ? current.sessionId : null,
        });
        setExpandedProjectId((current) => {
          return current && ordered.some((item) =>
            item.project_id === current && item.category_id === nextCategoryId
          )
            ? current
            : null;
        });
        hasLoadedCatalogRef.current = true;
        setState("ready");
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "项目列表载入失败。");
        if (!hasLoadedCatalogRef.current) {
          setState("error");
        }
      }
    };

    void load();
    return () => { cancelled = true; };
  }, [applySelection, getCategorySelection, requestKey, restoreSavedSelections, selectionRef]);

  const expandedProject = useMemo(
    () => items.find((item) => item.project_id === expandedProjectId) ?? null,
    [expandedProjectId, items],
  );
  const selectedCategory = useMemo(
    () => categories.find((category) => category.category_id === selectedCategoryId) ?? null,
    [categories, selectedCategoryId],
  );
  const selectedCategoryProjects = useMemo(
    () => getCategoryProjects(items, selectedCategoryId),
    [items, selectedCategoryId],
  );
  const selectedProject = useMemo(
    () => items.find((item) => item.project_id === selectedProjectId) ?? null,
    [items, selectedProjectId],
  );

  const collapseProject = useCallback(() => setExpandedProjectId(null), []);
  const createManagedProject = useCallback(async (projectKind: ProjectKind) => {
    setIsCreatingProject(true);
    setError(null);
    try {
      const activeCategoryId = selectionRef.current.categoryId;
      const createdProject = await createProjectRequest({
        category_id: activeCategoryId,
        project_kind: projectKind,
      });
      const nextItems = [...itemsRef.current, createdProject];
      itemsRef.current = nextItems;
      setItems(nextItems);
      selectNavigation({
        categoryId: createdProject.category_id, projectId: createdProject.project_id, sessionId: null,
      });
      setExpandedProjectId(null);
      setPendingRenameProjectId(createdProject.project_id);
      persistProjectOrderSilently(nextItems);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "项目创建失败。");
      throw createError;
    } finally {
      setIsCreatingProject(false);
    }
  }, [selectNavigation, selectionRef]);
  const createProject = useCallback(
    () => createManagedProject("project"),
    [createManagedProject],
  );
  const createKnowledgeProject = useCallback(
    () => createManagedProject("knowledge"),
    [createManagedProject],
  );
  const createExperienceProject = useCallback(
    () => createManagedProject("experience"),
    [createManagedProject],
  );
  const createThemeProject = useCallback(
    () => createManagedProject("theme"),
    [createManagedProject],
  );
  const createCategory = useCallback(async (categoryKind: ProjectKind) => {
    setIsCreatingProjectCategory(true);
    setError(null);
    try {
      const createdCategory = await createProjectCategoryRequest(
        null,
        categoryKind,
      );
      const nextCategories = [...categoriesRef.current, createdCategory];
      categoriesRef.current = nextCategories;
      setCategories(nextCategories);
      selectNavigation({ categoryId: createdCategory.category_id, projectId: null, sessionId: null }, categoryKind === "project");
      setExpandedProjectId(null);
      setPendingRenameCategoryId(createdCategory.category_id);
    } catch (createError) {
      setError(createError instanceof Error
        ? createError.message
        : categoryKind === "role"
          ? "角色分类创建失败。"
          : categoryKind === "theme"
            ? "主题分类创建失败。"
          : "项目分类创建失败。");
      throw createError;
    } finally {
      setIsCreatingProjectCategory(false);
    }
  }, [selectNavigation]);
  const importProjectFolders = useCallback(async (
    rootPaths: string[],
  ): Promise<ProjectFolderImportBatchResult> => {
    setIsCreatingProject(true);
    setError(null);
    setDuplicateImportConflict(null);
    try {
      const activeCategoryId = selectionRef.current.categoryId;
      const result = await runProjectFolderImportBatch(
        rootPaths,
        (rootPath) => createProjectRequest({
          category_id: activeCategoryId,
          root_path: rootPath,
        }),
        parseProjectImportConflict,
      );

      if (result.createdProjects.length > 0) {
        const nextItems = [...itemsRef.current, ...result.createdProjects];
        const lastCreatedProject = result.createdProjects.at(-1)!;
        itemsRef.current = nextItems;
        setItems(nextItems);
        selectNavigation({
          categoryId: lastCreatedProject.category_id, projectId: lastCreatedProject.project_id, sessionId: null,
        });
        setExpandedProjectId(lastCreatedProject.project_id);
        persistProjectOrderSilently(nextItems);
      }

      setDuplicateImportConflict(result.conflicts[0] ?? null);
      if (result.failures.length > 0) {
        const firstError = result.failures[0].error;
        setError(firstError instanceof Error ? firstError.message : "项目导入失败。");
      }
      return result;
    } finally {
      setIsCreatingProject(false);
    }
  }, [selectNavigation, selectionRef]);
  const createProjectCategory = useCallback(
    () => createCategory("project"),
    [createCategory],
  );
  const createKnowledgeProjectCategory = useCallback(
    () => createCategory("knowledge"),
    [createCategory],
  );
  const createExperienceProjectCategory = useCallback(
    () => createCategory("experience"),
    [createCategory],
  );
  const createRoleProjectCategory = useCallback(
    () => createCategory("role"),
    [createCategory],
  );
  const createProviderProjectCategory = useCallback(
    () => createCategory("provider"),
    [createCategory],
  );
  const createThemeProjectCategory = useCallback(
    () => createCategory("theme"),
    [createCategory],
  );
  const createRoleProject = useCallback(async () => {
    setIsCreatingProject(true);
    setError(null);
    try {
      const createdProject = await createRoleProjectRequest({
        category_id: selectionRef.current.categoryId,
      });
      const nextItems = [...itemsRef.current, createdProject];
      itemsRef.current = nextItems;
      setItems(nextItems);
      selectNavigation({
        categoryId: createdProject.category_id, projectId: createdProject.project_id, sessionId: null,
      });
      setExpandedProjectId(null);
      setPendingRenameProjectId(createdProject.project_id);
      persistProjectOrderSilently(nextItems);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "角色创建失败。");
      throw createError;
    } finally {
      setIsCreatingProject(false);
    }
  }, [selectNavigation, selectionRef]);
  const createProjectsFromFolders = useCallback(async (
    rootPaths: string[],
  ): Promise<ProjectFolderImportSummary> => {
    const result = await importProjectFolders(rootPaths);
    return {
      conflictCount: result.conflicts.length,
      createdCount: result.createdProjects.length,
      failedCount: result.failures.length,
    };
  }, [importProjectFolders]);
  const createProjectFromFolder = useCallback(async (rootPath: string) => {
    const result = await importProjectFolders([rootPath]);
    if (result.failures.length > 0) {
      throw result.failures[0].error;
    }
  }, [importProjectFolders]);
  const deleteProjectCategory = useCallback(async (categoryId: string) => {
    setError(null);
    try {
      const deletingCategory = categoriesRef.current.find(
        (category) => category.category_id === categoryId,
      );
      await deleteProjectCategoryRequest(categoryId);
      if (
        deletingCategory
        && selectionRef.current.categoryId === deletingCategory.category_id
      ) {
        const fallbackCategory = categoriesRef.current.find(
          (category) =>
            category.category_kind === deletingCategory.category_kind
            && category.category_id !== deletingCategory.category_id,
        );
        selectNavigation(getCategorySelection(itemsRef.current, fallbackCategory?.category_id ?? null));
        setExpandedProjectId(null);
      }
      setRequestKey((current) => current + 1);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "项目分类删除失败。");
      // System recycling can partially succeed; refresh the completed removals.
      setRequestKey((current) => current + 1);
      throw deleteError;
    }
  }, [selectNavigation, getCategorySelection, selectionRef]);
  const deleteProject = useCallback(async (
    projectId: string,
    options: { deleteFiles?: boolean } = {},
  ) => {
    const project = itemsRef.current.find((item) => item.project_id === projectId);
    if (!project) throw new Error("项目不存在。");

    setDeletingProjectId(projectId);
    setError(null);
    try {
      await deleteProjectRequest(projectId, { deleteFiles: options.deleteFiles });
      const nextItems = itemsRef.current.filter((item) => item.project_id !== projectId);
      itemsRef.current = nextItems;
      setItems(nextItems);
      if (selectionRef.current.projectId === projectId) {
        selectNavigation(getCategorySelection(nextItems, selectionRef.current.categoryId));
      }
      setExpandedProjectId((current) => (current === projectId ? null : current));
      persistProjectOrderSilently(nextItems);
    } catch (deleteError) {
      throw deleteError;
    } finally {
      setDeletingProjectId((current) => (current === projectId ? null : current));
    }
  }, [selectNavigation, getCategorySelection, selectionRef]);
  const dismissImportConflict = useCallback(() => setDuplicateImportConflict(null), []);
  const selectProject = useCallback((projectId: string, sessionId?: string | null) => {
    const project = itemsRef.current.find((item) => item.project_id === projectId);
    // Kept-alive collections can still show this project while the catalog's
    // active category belongs to another collection. Restore both together.
    selectNavigation({
      categoryId: project?.category_id ?? selectionRef.current.categoryId,
      projectId,
      sessionId: sessionId ?? null,
    });
  }, [selectNavigation, selectionRef]);
  const expandProject = useCallback((projectId: string, sessionId?: string | null) => {
    selectProject(projectId, sessionId);
    setExpandedProjectId(projectId);
  }, [selectProject]);
  const getReorderedProjectIds = useCallback((
    activeId: string,
    targetId: string,
    position: "before" | "after",
  ) => {
    const ids = itemsRef.current.map((p) => p.project_id);
    const activeIndex = ids.indexOf(activeId);
    if (activeIndex === -1) return ids;
    const filtered = ids.filter((id) => id !== activeId);
    let targetIndex = filtered.indexOf(targetId);
    if (targetIndex === -1) return ids;
    if (position === "after") targetIndex += 1;
    filtered.splice(targetIndex, 0, activeId);
    return filtered;
  }, []);
  const jumpToImportConflictProject = useCallback(() => {
    const conflict = duplicateImportConflict;
    if (!conflict) return;
    selectNavigation({ categoryId: conflict.categoryId, projectId: conflict.projectId, sessionId: null });
    setExpandedProjectId(conflict.projectId);
    setDuplicateImportConflict(null);
  }, [selectNavigation, duplicateImportConflict]);
  const moveProjectToCategory = useCallback(async (projectId: string, categoryId: string) => {
    setError(null);
    try {
      const updated = await moveProjectToCategoryRequest(projectId, categoryId);
      const nextItems = itemsRef.current.map((p) =>
        p.project_id === projectId ? updated : p,
      );
      itemsRef.current = nextItems;
      setItems(nextItems);
      const activeCategoryId = selectionRef.current.categoryId;
      if (updated.category_id !== activeCategoryId) {
        if (selectionRef.current.projectId === projectId) {
          selectNavigation(getCategorySelection(nextItems, activeCategoryId));
        }
        setExpandedProjectId((current) => (current === projectId ? null : current));
      }
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "项目移动失败。");
      throw moveError;
    }
  }, [selectNavigation, getCategorySelection, selectionRef]);
  const pinProjectToCategoryTop = useCallback(async (projectId: string) => {
    const project = itemsRef.current.find((item) => item.project_id === projectId);
    if (!project) {
      throw new Error("项目不存在。");
    }

    const firstCategoryProject = itemsRef.current.find(
      (item) => item.category_id === project.category_id,
    );
    if (!firstCategoryProject || firstCategoryProject.project_id === projectId) {
      return;
    }

    const nextProjectIds = itemsRef.current
      .map((item) => item.project_id)
      .filter((id) => id !== projectId);
    const insertIndex = nextProjectIds.indexOf(firstCategoryProject.project_id);
    if (insertIndex < 0) {
      return;
    }

    nextProjectIds.splice(insertIndex, 0, projectId);
    setError(null);
    try {
      await saveProjectOrder(nextProjectIds);
      const nextItems = applyProjectOrder(itemsRef.current, nextProjectIds);
      itemsRef.current = nextItems;
      setItems(nextItems);
    } catch (pinError) {
      setError(pinError instanceof Error ? pinError.message : "项目置顶失败。");
      throw pinError;
    }
  }, []);
  const persistProjectOrder = useCallback(async (projectIds: string[]) => {
    await saveProjectOrder(projectIds);
    const nextItems = applyProjectOrder(itemsRef.current, projectIds);
    itemsRef.current = nextItems;
    setItems(nextItems);
  }, []);
  const previewProjectOrder = useCallback((projectIds: string[]) => {
    const nextItems = applyProjectOrder(itemsRef.current, projectIds);
    itemsRef.current = nextItems;
    setItems(nextItems);
  }, []);
  const revealProject = useCallback(async (projectId: string) => {
    setError(null);
    try {
      await revealProjectFileRequest(projectId, { path: "" });
    } catch (revealError) {
      setError(revealError instanceof Error
        ? revealError.message
        : "无法在资源管理器中显示项目。");
      throw revealError;
    }
  }, []);
  const reload = useCallback(() => setRequestKey((current) => current + 1), []);
  const renameProjectCategory = useCallback(async (categoryId: string, name: string) => {
    const normalizedName = name.trim();
    if (!normalizedName) throw new Error("项目分类名称不能为空。");
    setError(null);
    try {
      const updated = await renameProjectCategoryRequest(categoryId, normalizedName);
      const nextCategories = categoriesRef.current.map((category) =>
        category.category_id === categoryId ? updated : category,
      );
      categoriesRef.current = nextCategories;
      setCategories(nextCategories);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "项目分类重命名失败。");
      throw renameError;
    }
  }, []);
  const renameProject = useCallback(async (projectId: string, name: string) => {
    const normalizedName = name.trim();
    if (!normalizedName) throw new Error("项目名称不能为空。");
    setError(null);
    try {
      const updated = await renameProjectRequest(projectId, normalizedName);
      const nextItems = itemsRef.current.map((p) =>
        p.project_id === projectId ? updated : p,
      );
      itemsRef.current = nextItems;
      setItems(nextItems);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "项目重命名失败。");
      throw renameError;
    }
  }, []);
  const selectCategory = useCallback((
    categoryId: string,
    options: { persistWorkspaceSelection?: boolean } = {},
  ) => {
    selectNavigation(getCategorySelection(itemsRef.current, categoryId), options.persistWorkspaceSelection !== false);
    setError(null);
    setDuplicateImportConflict(null);
    setExpandedProjectId(null);
  }, [selectNavigation, getCategorySelection]);
  const confirmSessionSelection = useCallback((projectId: string, sessionId: string | null) => {
    if (selectionRef.current.projectId !== projectId) return;
    applySelection({ ...selectionRef.current, sessionId });
  }, [applySelection, selectionRef]);

  return useMemo(() => ({
    categories,
    collapseProject,
    clearPendingRenameCategory,
    clearPendingRenameProject,
    confirmSessionSelection,
    createProject,
    createKnowledgeProject,
    createExperienceProject,
    createRoleProject,
    createThemeProject,
    createProjectCategory,
    createKnowledgeProjectCategory,
    createExperienceProjectCategory,
    createRoleProjectCategory,
    createProviderProjectCategory,
    createThemeProjectCategory,
    createProjectFromFolder,
    createProjectsFromFolders,
    deleteProjectCategory,
    deleteProject,
    deletingProjectId,
    dismissImportConflict,
    duplicateImportConflict,
    error,
    expandedProject,
    expandedProjectId,
    expandProject,
    getReorderedProjectIds,
    isCreatingProjectCategory,
    isCreatingProject,
    items,
    jumpToImportConflictProject,
    moveProjectToCategory,
    pendingRenameCategoryId,
    pendingRenameProjectId,
    pinProjectToCategoryTop,
    persistProjectOrder,
    previewProjectOrder,
    revealProject,
    reload,
    renameProjectCategory,
    renameProject,
    selectedCategory,
    selectedCategoryId,
    selectedCategoryProjects,
    selectedProject,
    selectedProjectId,
    selectedSessionId,
    selectCategory,
    selectProject,
    state,
  }), [
    categories,
    clearPendingRenameCategory,
    clearPendingRenameProject,
    collapseProject,
    confirmSessionSelection,
    createProject,
    createKnowledgeProject,
    createExperienceProject,
    createRoleProject,
    createThemeProject,
    createProjectCategory,
    createKnowledgeProjectCategory,
    createExperienceProjectCategory,
    createRoleProjectCategory,
    createProviderProjectCategory,
    createThemeProjectCategory,
    createProjectFromFolder,
    createProjectsFromFolders,
    deleteProject,
    deleteProjectCategory,
    deletingProjectId,
    dismissImportConflict,
    duplicateImportConflict,
    error,
    expandProject,
    expandedProject,
    expandedProjectId,
    getReorderedProjectIds,
    isCreatingProject,
    isCreatingProjectCategory,
    items,
    jumpToImportConflictProject,
    moveProjectToCategory,
    pendingRenameCategoryId,
    pendingRenameProjectId,
    pinProjectToCategoryTop,
    persistProjectOrder,
    previewProjectOrder,
    revealProject,
    reload,
    renameProject,
    renameProjectCategory,
    selectCategory,
    selectProject,
    selectedCategory,
    selectedCategoryId,
    selectedCategoryProjects,
    selectedProject,
    selectedProjectId,
    selectedSessionId,
    state,
  ]);
}
