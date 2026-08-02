import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import "./workspace-layout.css";

import { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import { useProviderCatalog } from "../../../features/provider-catalog/model/useProviderCatalog";
import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import { useToolCatalog } from "../../../features/tool-catalog/model/useToolCatalog";
import { useToolFolders } from "../../../features/tool-catalog/model/useToolFolders";
import { useToolFolderBrowser } from "../../../features/tool-browser/model/useToolFolderBrowser";
import type { FunctionalModelSettingsSectionId } from "../../../features/functional-model-settings/model/functionalModelSections";
import { useFunctionalModelSectionSelection } from "../../../features/functional-model-settings/model/useFunctionalModelSectionSelection";
import { HoverSidebar } from "../../../widgets/hover-sidebar/ui/HoverSidebar";
import type {
  HoverSidebarSectionId,
  HoverSidebarTransitionDirection,
} from "../../../widgets/hover-sidebar/model/sidebarSections";
import { WindowTitlebar } from "../../../widgets/window-titlebar/ui/WindowTitlebar";
import { useProviderModelDiscovery } from "../../../features/provider-model-discovery/model/useProviderModelDiscovery";
import { useProjectCatalog } from "../../../features/project-catalog/model/useProjectCatalog";
import type {
  ProjectFileDragData,
  ProjectFileReferenceRequest,
} from "../../../entities/project/model/projectFileDragData";
import type {
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import {
  normalizeWorkspaceLayoutPreferences,
  normalizeWorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import {
  preloadProjectEntry,
  type ProjectEntryWarmupOptions,
} from "../../../features/project-entry/model/projectEntryWarmup";
import { useProviderConfigState } from "../../../features/provider-config/model/useProviderConfigState";
import { useSidePanelLayout } from "../model/useSidePanelLayout";
import { collectToolEntryFilePaths } from "../model/toolEntryFiles";
import { useProjectWorkspaceTabsPersistence } from "../model/useProjectWorkspaceTabsPersistence";
import { useToolWorkspacePersistence } from "../model/useToolWorkspacePersistence";
import { useWorkspaceUnsavedChangesGuard } from "../model/useWorkspaceUnsavedChangesGuard";
import {
  getWorkspaceProjectKind,
  useWorkspaceProjectCollections,
} from "../model/useWorkspaceProjectCollections";
import {
  buildHoverProjectCatalog,
  buildHoverThemeCatalog,
  buildSidePanelProjectCatalog,
} from "../model/workspaceProjectCatalogAdapters";
import type { WorkspaceSettingsSectionId } from "../model/workspaceSettingsSections";
import { markFrontendStartup } from "../../../shared/model/startup-timing/startupTiming";
import { WorkspaceNavigationProvider } from "../../../shared/model/workspaceNavigation";
import type { AppThemeControl } from "../../../shared/theme";
import { revealProjectFile } from "../../../services/project/revealProjectFile";
import { saveWorkspaceLayoutPreferences } from "../../../services/workspace/workspaceLayoutPreferences";
import { usePageStatusBar } from "../../../widgets/app-frame/model/appStatusBar";
import { WorkspaceCanvasPanel } from "./WorkspaceCanvasPanel";
import { WorkspaceSidePanel } from "./WorkspaceSidePanel";
import { WorkspaceStatusPath } from "./WorkspaceStatusPath";
import { WorkspaceUnsavedChangesModal } from "./WorkspaceUnsavedChangesModal";

const PRIMARY_SIDEBAR_COLLAPSED_WIDTH = 52;
const APP_STATUS_BAR_INLINE_PADDING = 12;

type WorkspacePageProps = {
  initialLayoutPreferences: WorkspaceLayoutPreferences | null;
  onInitialWorkspaceSettled: () => void;
  themeControl: AppThemeControl;
};

export function WorkspacePage({
  initialLayoutPreferences,
  onInitialWorkspaceSettled,
  themeControl,
}: WorkspacePageProps) {
  const [activeSection, setActiveSection] =
    useState<HoverSidebarSectionId>("overview");
  const [layoutPreferences, setLayoutPreferences] = useState(() =>
    normalizeWorkspaceLayoutPreferences(initialLayoutPreferences),
  );
  const functionalModelSectionSelection = useFunctionalModelSectionSelection(true);
  const [activeSettingsSectionId, setActiveSettingsSectionId] =
    useState<WorkspaceSettingsSectionId>(functionalModelSectionSelection.activeSectionId);
  const [sidePanelTransitionDirection, setSidePanelTransitionDirection] =
    useState<HoverSidebarTransitionDirection>("down");
  const projectFileReferenceRequestIdRef = useRef(0);
  const layoutPreferenceSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const [projectFileReferenceRequest, setProjectFileReferenceRequest] =
    useState<ProjectFileReferenceRequest | null>(null);
  const initialCatalogsReadyLoggedRef = useRef(false);
  const initialWorkspaceSettledNotifiedRef = useRef(false);
  const projectCatalog = useProjectCatalog();
  const projectCollections = useWorkspaceProjectCollections(projectCatalog);
  const {
    categories: projectCategories,
    expandedProject: projectExpandedProject,
    projects: ordinaryProjects,
    selectedCategoryId: projectSelectedCategoryId,
    selectedProject: projectSelectedProject,
    selectedSessionId: projectSelectedSessionId,
  } = projectCollections.collections.project;
  const {
    categories: knowledgeProjectCategories,
    expandedProject: knowledgeExpandedProject,
    projects: knowledgeProjects,
    selectedCategoryId: knowledgeSelectedCategoryId,
    selectedProject: knowledgeSelectedProject,
    selectedSessionId: knowledgeSelectedSessionId,
  } = projectCollections.collections.knowledge;
  const {
    categories: experienceProjectCategories,
    expandedProject: experienceExpandedProject,
    projects: experienceProjects,
    selectedCategoryId: experienceSelectedCategoryId,
    selectedProject: experienceSelectedProject,
    selectedSessionId: experienceSelectedSessionId,
  } = projectCollections.collections.experience;
  const {
    categories: roleProjectCategories,
    expandedProject: roleExpandedProject,
    projects: roleProjects,
    selectedCategoryId: roleSelectedCategoryId,
    selectedProject: roleSelectedProject,
    selectedSessionId: roleSelectedSessionId,
  } = projectCollections.collections.role;
  const {
    categories: themeProjectCategories,
    expandedProject: themeExpandedProject,
    projects: themeProjects,
    selectedCategoryId: themeSelectedCategoryId,
    selectedProject: themeSelectedProject,
    selectedSessionId: themeSelectedSessionId,
  } = projectCollections.collections.theme;
  const {
    categories: providerProjectCategories,
    expandedProject: providerExpandedProject,
    projects: providerProjects,
    selectedCategoryId: providerSelectedCategoryId,
    selectedProject: providerSelectedProject,
    selectedSessionId: providerSelectedSessionId,
  } = projectCollections.collections.provider;
  const providerCatalog = useProviderCatalog();
  const toolCatalog = useToolCatalog();
  const providerConfigState = useProviderConfigState(
    providerCatalog.items,
    providerCatalog.selectedProviderId,
  );
  const providerModelDiscovery = useProviderModelDiscovery(providerCatalog.selectedProviderId);
  const selectedProviderProject = useMemo(
    () => providerProjects.find(
      (project) => getProviderIdFromProject(project.root_path) === providerCatalog.selectedProviderId,
    ) ?? null,
    [providerCatalog.selectedProviderId, providerProjects],
  );
  const providerCatalogIdentityKey = providerCatalog.items
    .map((provider) => `${provider.provider_id}:${provider.display_name}`)
    .join("\n");

  useEffect(() => {
    if (providerCatalog.state !== "ready") return;
    projectCatalog.reload();
  }, [providerCatalog.state, providerCatalogIdentityKey, projectCatalog.reload]);

  useEffect(() => {
    if (activeSection !== "models" || !selectedProviderProject) return;
    if (projectCatalog.selectedCategoryId !== selectedProviderProject.category_id) {
      projectCatalog.selectCategory(selectedProviderProject.category_id);
    }
    if (projectCatalog.selectedProjectId !== selectedProviderProject.project_id) {
      projectCatalog.selectProject(selectedProviderProject.project_id);
    }
  }, [
    activeSection,
    projectCatalog.selectCategory,
    projectCatalog.selectProject,
    projectCatalog.selectedCategoryId,
    projectCatalog.selectedProjectId,
    selectedProviderProject,
  ]);
  const handleLayoutPreferenceChange = useCallback((update: WorkspaceLayoutPreferenceUpdate) => {
    const normalizedUpdate = normalizeWorkspaceLayoutPreferenceUpdate(update);
    if (Object.keys(normalizedUpdate).length === 0) {
      return;
    }

    setLayoutPreferences((current) => {
      const projectOverviewMaximizedProjectIds = {
        ...current.projectOverviewMaximizedProjectIds,
      };
      const projectOverviewViews = {
        ...current.projectOverviewViews,
      };
      const toolOverviewViews = {
        ...current.toolOverviewViews,
      };
      const collectionOverviewViews = {
        ...current.collectionOverviewViews,
      };
      if (normalizedUpdate.projectOverviewMaximized) {
        const { categoryId, projectId } = normalizedUpdate.projectOverviewMaximized;
        if (projectId) {
          projectOverviewMaximizedProjectIds[categoryId] = projectId;
        } else {
          delete projectOverviewMaximizedProjectIds[categoryId];
        }
      }
      if (normalizedUpdate.projectOverviewView) {
        projectOverviewViews[normalizedUpdate.projectOverviewView.categoryId] =
          normalizedUpdate.projectOverviewView.view;
      }
      if (normalizedUpdate.toolOverviewView) {
        toolOverviewViews[normalizedUpdate.toolOverviewView.categoryId] =
          normalizedUpdate.toolOverviewView.view;
      }
      if (normalizedUpdate.collectionOverviewView) {
        collectionOverviewViews[normalizedUpdate.collectionOverviewView.categoryId] =
          normalizedUpdate.collectionOverviewView.view;
      }
      return normalizeWorkspaceLayoutPreferences({
        ...current,
        ...normalizedUpdate,
        projectOverviewLayoutModes: normalizedUpdate.projectOverviewLayout
          ? {
              ...current.projectOverviewLayoutModes,
              [normalizedUpdate.projectOverviewLayout.categoryId]:
                normalizedUpdate.projectOverviewLayout.layoutMode,
            }
          : current.projectOverviewLayoutModes,
        projectOverviewMaximizedProjectIds,
        projectOverviewViews,
        toolOverviewViews,
        collectionOverviewViews,
      });
    });
    layoutPreferenceSaveQueueRef.current = layoutPreferenceSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        await saveWorkspaceLayoutPreferences(normalizedUpdate);
      })
      .catch((error) => {
        console.warn("Failed to save workspace layout preferences.", error);
      });
  }, []);
  const sidePanelLayout = useSidePanelLayout({
    initialWidth: layoutPreferences.sidePanelWidth,
    onWidthCommit: (sidePanelWidth) => {
      handleLayoutPreferenceChange({ sidePanelWidth });
    },
  });
  const projectDocumentTabs = useDocumentTabs();
  const toolDocumentTabs = useDocumentTabs();
  const {
    modal: unsavedChangesModal,
    requestTransition: requestUnsavedTransition,
  } = useWorkspaceUnsavedChangesGuard();
  const toolFolders = useToolFolders(
    toolCatalog.selectedToolset?.category_id ?? null,
    {
      readonly: !canModifyToolFolders(toolCatalog.selectedToolset),
    },
  );
  const displayedToolset = useMemo(
    () => toolFolders.displayedToolsetId
      ? toolCatalog.items.find((item) => item.category_id === toolFolders.displayedToolsetId) ?? null
      : toolCatalog.selectedToolset,
    [toolCatalog.items, toolCatalog.selectedToolset, toolFolders.displayedToolsetId],
  );
  const toolBrowser = useToolFolderBrowser(
    toolFolders.displayedToolsetId,
    toolFolders.expandedFolderId,
  );
  const handlePrepareProject = useCallback((projectId: string) => {
    void preloadProjectEntry(projectId);
  }, []);
  const handleExpandProject = useCallback(async (
    projectId: string,
    options: ProjectEntryWarmupOptions = {},
  ) => {
    const expand = async () => {
      projectCatalog.expandProject(projectId, options.sessionId ?? null);
      await preloadProjectEntry(projectId, options);
    };
    if (projectId === projectCatalog.selectedProjectId) {
      await expand();
      return true;
    }
    return requestUnsavedTransition(
      [projectDocumentTabs],
      "switch",
      expand,
    );
  }, [
    projectCatalog.expandProject,
    projectCatalog.selectedProjectId,
    projectDocumentTabs,
    requestUnsavedTransition,
  ]);
  const handleOpenProvider = useCallback((providerId: string) => {
    const providerProject = providerProjects.find(
      (project) => getProviderIdFromProject(project.root_path) === providerId,
    );
    if (!providerProject) {
      projectCatalog.reload();
      return;
    }
    providerCatalog.selectProvider(providerId);
    projectCatalog.selectCategory(providerProject.category_id);
    void handleExpandProject(providerProject.project_id);
  }, [
    handleExpandProject,
    projectCatalog.reload,
    projectCatalog.selectCategory,
    providerCatalog.selectProvider,
    providerProjects,
  ]);
  const handleSelectProject = useCallback(async (
    projectId: string,
    options: ProjectEntryWarmupOptions = {},
  ) => {
    const select = async () => {
      projectCatalog.selectProject(projectId, options.sessionId ?? null);
      await preloadProjectEntry(projectId, options);
    };
    if (projectId === projectCatalog.selectedProjectId) {
      await select();
      return true;
    }
    return requestUnsavedTransition(
      [projectDocumentTabs],
      "switch",
      select,
    );
  }, [
    projectCatalog.selectProject,
    projectCatalog.selectedProjectId,
    projectDocumentTabs,
    requestUnsavedTransition,
  ]);
  const handleCollapseProject = useCallback(() => {
    return requestUnsavedTransition(
      [projectDocumentTabs],
      "return",
      projectCatalog.collapseProject,
    );
  }, [projectCatalog.collapseProject, projectDocumentTabs, requestUnsavedTransition]);
  const handleSelectProjectCategory = useCallback((categoryId: string) => {
    if (categoryId === projectCatalog.selectedCategoryId) return;
    const category = projectCatalog.categories.find(
      (item) => item.category_id === categoryId,
    );
    void requestUnsavedTransition(
      [projectDocumentTabs],
      "switch",
      () => projectCatalog.selectCategory(categoryId, {
        persistWorkspaceSelection: category?.category_kind === "project",
      }),
    );
  }, [
    projectCatalog.categories,
    projectCatalog.selectCategory,
    projectCatalog.selectedCategoryId,
    projectDocumentTabs,
    requestUnsavedTransition,
  ]);
  const handleJumpToImportConflictProject = useCallback(() => {
    void requestUnsavedTransition(
      [projectDocumentTabs],
      "switch",
      projectCatalog.jumpToImportConflictProject,
    );
  }, [
    projectCatalog.jumpToImportConflictProject,
    projectDocumentTabs,
    requestUnsavedTransition,
  ]);
  const handleRequestCloseWindow = useCallback((closeWindow: () => Promise<void>) => {
    void requestUnsavedTransition(
      [projectDocumentTabs, toolDocumentTabs],
      "exit",
      closeWindow,
    );
  }, [projectDocumentTabs, requestUnsavedTransition, toolDocumentTabs]);
  const handleCollapseToolFolder = useCallback(() => {
    return requestUnsavedTransition(
      [toolDocumentTabs],
      "return",
      toolFolders.collapseFolder,
    );
  }, [requestUnsavedTransition, toolDocumentTabs, toolFolders.collapseFolder]);
  const handleOpenToolFolder = useCallback((folderId: string) => {
    if (folderId === toolFolders.expandedFolderId) return;
    void requestUnsavedTransition(
      [toolDocumentTabs],
      "switch",
      () => toolFolders.expandFolder(folderId),
    );
  }, [
    requestUnsavedTransition,
    toolDocumentTabs,
    toolFolders.expandFolder,
    toolFolders.expandedFolderId,
  ]);
  const handleSelectToolset = useCallback((toolsetId: string) => {
    if (toolsetId === toolCatalog.selectedToolsetId) return;
    void requestUnsavedTransition(
      [toolDocumentTabs],
      "switch",
      () => toolCatalog.selectToolset(toolsetId),
    );
  }, [
    requestUnsavedTransition,
    toolCatalog.selectToolset,
    toolCatalog.selectedToolsetId,
    toolDocumentTabs,
  ]);
  const guardedToolFolders = useMemo(() => ({
    ...toolFolders,
    collapseFolder: handleCollapseToolFolder,
    expandFolder: handleOpenToolFolder,
  }), [handleCollapseToolFolder, handleOpenToolFolder, toolFolders]);
  const hoverSidebarProjectCatalog = useMemo(() => buildHoverProjectCatalog({
    catalog: projectCatalog,
    categories: projectCategories,
    createCategory: projectCatalog.createProjectCategory,
    kind: "project",
    selectedCategoryId: projectSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, projectCategories, projectSelectedCategoryId, handleSelectProjectCategory]);
  const hoverSidebarToolCatalog = useMemo(() => ({
    clearPendingRenameToolset: toolCatalog.clearPendingRenameToolset,
    createToolset: toolCatalog.createToolset,
    deleteToolset: toolCatalog.deleteToolset,
    error: toolCatalog.error,
    isCreatingToolset: toolCatalog.isCreatingToolset,
    items: toolCatalog.items,
    pendingRenameToolsetId: toolCatalog.pendingRenameToolsetId,
    renameToolset: toolCatalog.renameToolset,
    selectedToolsetId: toolCatalog.selectedToolsetId,
    selectToolset: handleSelectToolset,
    state: toolCatalog.state,
  }), [
    toolCatalog.clearPendingRenameToolset,
    toolCatalog.createToolset,
    toolCatalog.deleteToolset,
    toolCatalog.error,
    toolCatalog.isCreatingToolset,
    toolCatalog.items,
    toolCatalog.pendingRenameToolsetId,
    toolCatalog.renameToolset,
    toolCatalog.selectedToolsetId,
    handleSelectToolset,
    toolCatalog.state,
  ]);
  const sidePanelProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: projectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createProject,
    duplicateImportConflict: projectCatalog.duplicateImportConflict,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: projectExpandedProject,
    items: ordinaryProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "project",
    prepareProject: handlePrepareProject,
    selectedCategoryId: projectSelectedCategoryId,
    selectedProject: projectSelectedProject,
  }), [projectCatalog, projectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, projectExpandedProject, ordinaryProjects, handleJumpToImportConflictProject, handlePrepareProject, projectSelectedCategoryId, projectSelectedProject]);
  const hoverSidebarKnowledgeCatalog = useMemo(() => buildHoverProjectCatalog({
    catalog: projectCatalog,
    categories: knowledgeProjectCategories,
    createCategory: projectCatalog.createKnowledgeProjectCategory,
    kind: "knowledge",
    selectedCategoryId: knowledgeSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, knowledgeProjectCategories, knowledgeSelectedCategoryId, handleSelectProjectCategory]);
  const sidePanelKnowledgeProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: knowledgeProjectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createKnowledgeProject,
    duplicateImportConflict: null,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: knowledgeExpandedProject,
    items: knowledgeProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "knowledge",
    prepareProject: handlePrepareProject,
    selectedCategoryId: knowledgeSelectedCategoryId,
    selectedProject: knowledgeSelectedProject,
  }), [projectCatalog, knowledgeProjectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, knowledgeExpandedProject, knowledgeProjects, handleJumpToImportConflictProject, handlePrepareProject, knowledgeSelectedCategoryId, knowledgeSelectedProject]);
  const hoverSidebarExperienceCatalog = useMemo(() => buildHoverProjectCatalog({
    catalog: projectCatalog,
    categories: experienceProjectCategories,
    createCategory: projectCatalog.createExperienceProjectCategory,
    kind: "experience",
    selectedCategoryId: experienceSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, experienceProjectCategories, experienceSelectedCategoryId, handleSelectProjectCategory]);
  const sidePanelExperienceProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: experienceProjectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createExperienceProject,
    duplicateImportConflict: null,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: experienceExpandedProject,
    items: experienceProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "experience",
    prepareProject: handlePrepareProject,
    selectedCategoryId: experienceSelectedCategoryId,
    selectedProject: experienceSelectedProject,
  }), [projectCatalog, experienceProjectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, experienceExpandedProject, experienceProjects, handleJumpToImportConflictProject, handlePrepareProject, experienceSelectedCategoryId, experienceSelectedProject]);
  const handleSelectToolFolder = useCallback((folderId: string) => {
    toolFolders.selectFolder(folderId);
  }, [toolFolders.selectFolder]);
  const hoverSidebarRoleCatalog = useMemo(() => buildHoverProjectCatalog({
    catalog: projectCatalog,
    categories: roleProjectCategories,
    createCategory: projectCatalog.createRoleProjectCategory,
    kind: "role",
    selectedCategoryId: roleSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, roleProjectCategories, roleSelectedCategoryId, handleSelectProjectCategory]);
  const sidePanelRoleProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: roleProjectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createRoleProject,
    duplicateImportConflict: null,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: roleExpandedProject,
    items: roleProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "role",
    prepareProject: handlePrepareProject,
    selectedCategoryId: roleSelectedCategoryId,
    selectedProject: roleSelectedProject,
  }), [projectCatalog, roleProjectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, roleExpandedProject, roleProjects, handleJumpToImportConflictProject, handlePrepareProject, roleSelectedCategoryId, roleSelectedProject]);
  const hoverSidebarThemeCatalog = useMemo(() => buildHoverThemeCatalog({
    catalog: projectCatalog,
    categories: themeProjectCategories,
    createCategory: projectCatalog.createThemeProjectCategory,
    items: themeProjects,
    kind: "theme",
    selectedCategoryId: themeSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, themeProjectCategories, themeProjects, themeSelectedCategoryId, handleSelectProjectCategory]);
  const handleDeleteProviderCategory = useCallback(async (categoryId: string) => {
    await projectCatalog.deleteProjectCategory(categoryId);
    providerCatalog.reload();
    emitLlmModelCatalogChanged();
  }, [projectCatalog.deleteProjectCategory, providerCatalog.reload]);
  const hoverSidebarProviderCatalog = useMemo(() => buildHoverProjectCatalog({
    catalog: projectCatalog,
    categories: providerProjectCategories,
    createCategory: projectCatalog.createProviderProjectCategory,
    deleteCategory: handleDeleteProviderCategory,
    kind: "provider",
    selectedCategoryId: providerSelectedCategoryId,
    selectCategory: handleSelectProjectCategory,
  }), [projectCatalog, providerProjectCategories, providerSelectedCategoryId, handleSelectProjectCategory, handleDeleteProviderCategory]);
  const sidePanelThemeProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: themeProjectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createThemeProject,
    duplicateImportConflict: null,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: themeExpandedProject,
    items: themeProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "theme",
    prepareProject: handlePrepareProject,
    selectedCategoryId: themeSelectedCategoryId,
    selectedProject: themeSelectedProject,
  }), [projectCatalog, themeProjectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, themeExpandedProject, themeProjects, handleJumpToImportConflictProject, handlePrepareProject, themeSelectedCategoryId, themeSelectedProject]);
  const sidePanelProviderProjectCatalog = useMemo(() => buildSidePanelProjectCatalog({
    catalog: projectCatalog,
    categories: providerProjectCategories,
    collapseProject: handleCollapseProject,
    createProject: projectCatalog.createProject,
    duplicateImportConflict: null,
    expandProject: handleExpandProject,
    selectProject: handleSelectProject,
    expandedProject: providerExpandedProject,
    items: providerProjects,
    jumpToImportConflictProject: handleJumpToImportConflictProject,
    kind: "provider",
    prepareProject: handlePrepareProject,
    selectedCategoryId: providerSelectedCategoryId,
    selectedProject: providerSelectedProject,
  }), [projectCatalog, providerProjectCategories, handleCollapseProject, handleExpandProject, handleSelectProject, providerExpandedProject, providerProjects, handleJumpToImportConflictProject, handlePrepareProject, providerSelectedCategoryId, providerSelectedProject]);
  const sidePanelToolCatalog = useMemo(() => ({
    error: toolCatalog.error,
    items: toolCatalog.items,
    reload: toolCatalog.reload,
    selectedToolset: toolCatalog.selectedToolset,
    state: toolCatalog.state,
  }), [
    toolCatalog.error,
    toolCatalog.items,
    toolCatalog.reload,
    toolCatalog.selectedToolset,
    toolCatalog.state,
  ]);

  useEffect(() => {
    markFrontendStartup("frontend: WorkspacePage mounted");
  }, []);

  useEffect(() => {
    if (projectCatalog.state !== "loading") {
      markFrontendStartup(`frontend: project catalog ${projectCatalog.state}`);
    }
  }, [projectCatalog.state]);

  useEffect(() => {
    if (toolCatalog.state !== "loading") {
      markFrontendStartup(`frontend: tool catalog ${toolCatalog.state}`);
    }
  }, [toolCatalog.state]);

  useEffect(() => {
    if (providerCatalog.state !== "loading") {
      markFrontendStartup(`frontend: provider catalog ${providerCatalog.state}`);
    }
  }, [providerCatalog.state]);

  useEffect(() => {
    if (!providerConfigState.isLoading) {
      markFrontendStartup("frontend: provider configs ready");
    }
  }, [providerConfigState.isLoading]);

  useEffect(() => {
    if (
      initialWorkspaceSettledNotifiedRef.current ||
      projectCatalog.state === "loading" ||
      toolCatalog.state === "loading" ||
      providerCatalog.state === "loading" ||
      (providerConfigState.isLoading && !providerConfigState.error)
    ) {
      return;
    }

    initialWorkspaceSettledNotifiedRef.current = true;
    markFrontendStartup("frontend: workspace initial content settled");
    onInitialWorkspaceSettled();
  }, [
    onInitialWorkspaceSettled,
    projectCatalog.state,
    providerCatalog.state,
    providerConfigState.error,
    providerConfigState.isLoading,
    toolCatalog.state,
  ]);

  useEffect(() => {
    if (
      initialCatalogsReadyLoggedRef.current ||
      projectCatalog.state !== "ready" ||
      toolCatalog.state !== "ready" ||
      providerCatalog.state !== "ready" ||
      providerConfigState.isLoading
    ) {
      return;
    }

    initialCatalogsReadyLoggedRef.current = true;
    markFrontendStartup("frontend: workspace initial catalogs ready");
  }, [
    projectCatalog.state,
    providerCatalog.state,
    providerConfigState.isLoading,
    toolCatalog.state,
  ]);

  useEffect(() => {
    if (activeSection !== "tools") return undefined;

    const reloadToolFolders = () => toolFolders.reload();
    reloadToolFolders();

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        reloadToolFolders();
      }
    };
    window.addEventListener("focus", reloadToolFolders);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("focus", reloadToolFolders);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [activeSection, toolFolders.reload]);

  // ---- Ctrl+S 全局保存 ----
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        if (e.target instanceof HTMLElement && e.target.closest(".cm-editor")) {
          return;
        }
        e.preventDefault();
        const activeTabs = activeSection === "tools" ? toolDocumentTabs : projectDocumentTabs;
        void activeTabs.saveActiveTab();
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [activeSection, projectDocumentTabs, toolDocumentTabs]);

  // ---- 工作区状态持久化 ----
  const activeSectionPid = projectCatalog.selectedProjectId;
  const activeToolFolder = toolFolders.expandedFolder;
  const activeToolsetId = toolFolders.displayedToolsetId;
  const projectWorkspaceTabs = useProjectWorkspaceTabsPersistence({
    documentTabs: projectDocumentTabs,
    isRoleProject: projectCatalog.selectedProject?.project_kind === "role",
    isThemeProject: projectCatalog.selectedProject?.project_kind === "theme",
    projectId: activeSectionPid,
  });
  const toolWorkspaceTabs = useToolWorkspacePersistence({
    activeToolFolder,
    activeToolsetId,
    browser: toolBrowser,
    documentTabs: toolDocumentTabs,
  });
  const activeToolWorkspaceKey = toolWorkspaceTabs.activeWorkspaceKey;
  const toolEntryFilePaths = useMemo(
    () => collectToolEntryFilePaths(toolBrowser.treeData),
    [toolBrowser.treeData],
  );
  const handleCreateOverviewProject = useCallback(async () => {
    await projectCatalog.createProject();
  }, [projectCatalog.createProject]);
  const handleCreateKnowledgeProject = useCallback(async () => {
    await projectCatalog.createKnowledgeProject();
  }, [projectCatalog.createKnowledgeProject]);
  const handleCreateExperienceProject = useCallback(async () => {
    await projectCatalog.createExperienceProject();
  }, [projectCatalog.createExperienceProject]);
  const handleCreateRoleProject = useCallback(async () => {
    await projectCatalog.createRoleProject();
  }, [projectCatalog.createRoleProject]);

  const handleImportOverviewProjectFolder = useCallback(async (rootPath: string) => {
    await projectCatalog.createProjectFromFolder(rootPath);
  }, [projectCatalog.createProjectFromFolder]);
  const handleSectionSelect = useCallback((
    sectionId: HoverSidebarSectionId,
    direction: HoverSidebarTransitionDirection,
    explicitCatalogItemId?: string,
  ) => {
    if (sectionId === activeSection) {
      return;
    }
    void requestUnsavedTransition(
      [projectDocumentTabs, toolDocumentTabs],
      "switch",
      () => {
        const projectKind = getWorkspaceProjectKind(sectionId);
        if (explicitCatalogItemId && sectionId === "tools") {
          toolCatalog.selectToolset(explicitCatalogItemId);
        } else if (explicitCatalogItemId && projectKind) {
          projectCatalog.selectCategory(explicitCatalogItemId, {
            persistWorkspaceSelection: projectKind === "project",
          });
        } else if (projectKind) {
          projectCollections.activate(projectKind);
        }
        setSidePanelTransitionDirection(direction);
        setActiveSection(sectionId);
      },
    );
  }, [
    activeSection,
    projectCollections.activate,
    projectDocumentTabs,
    requestUnsavedTransition,
    projectCatalog.selectCategory,
    toolCatalog.selectToolset,
    toolDocumentTabs,
  ]);
  const handleSelectFunctionalModelSection = useCallback((
    sectionId: FunctionalModelSettingsSectionId,
  ) => {
    setActiveSettingsSectionId(sectionId);
    functionalModelSectionSelection.selectSection(sectionId);
  }, [functionalModelSectionSelection]);
  const handleSelectTokenEstimationSettings = useCallback(() => {
    setActiveSettingsSectionId("token-estimation");
  }, []);
  const handleSelectLanguageSettings = useCallback(() => {
    setActiveSettingsSectionId("language");
  }, []);
  const handleSelectGithubSettings = useCallback(() => {
    setActiveSettingsSectionId("github");
  }, []);
  const handleOpenGithubSettings = useCallback(() => {
    setActiveSettingsSectionId("github");
    handleSectionSelect("settings", "down");
  }, [handleSectionSelect]);
  const workspaceNavigation = useMemo(
    () => ({ openGithubSettings: handleOpenGithubSettings }),
    [handleOpenGithubSettings],
  );
  const handleSelectNetworkSettings = useCallback(() => {
    setActiveSettingsSectionId("network");
  }, []);
  const handleReferenceProjectFile = useCallback((file: ProjectFileDragData) => {
    projectFileReferenceRequestIdRef.current += 1;
    setProjectFileReferenceRequest({
      ...file,
      requestId: projectFileReferenceRequestIdRef.current,
    });
  }, []);
  const statusBarProject = (
    activeSection === "overview"
    || activeSection === "knowledge"
    || activeSection === "experience"
    || activeSection === "roles"
    || activeSection === "themes"
  ) &&
    projectCatalog.expandedProjectId &&
    projectCatalog.selectedProject?.project_id === projectCatalog.expandedProjectId
    ? projectCatalog.selectedProject
    : null;
  const statusBarActiveProjectFilePath = statusBarProject &&
    projectDocumentTabs.activeTab?.projectId === statusBarProject.project_id
    ? projectDocumentTabs.activeTab.projectFilePath
    : null;
  const statusBarPathLabel = statusBarProject
    ? buildProjectStatusPathLabel(statusBarProject.root_path, statusBarActiveProjectFilePath)
    : "";
  const statusBarPathMaxWidth = Math.max(
    0,
    PRIMARY_SIDEBAR_COLLAPSED_WIDTH +
      sidePanelLayout.sidePanelWidth -
      APP_STATUS_BAR_INLINE_PADDING,
  );
  const handleRevealStatusBarPath = useCallback(() => {
    if (!statusBarProject) return;
    void revealProjectFile(statusBarProject.project_id, {
      path: statusBarActiveProjectFilePath ?? "",
    }).catch(() => undefined);
  }, [statusBarActiveProjectFilePath, statusBarProject]);

  usePageStatusBar(
    () => ({
      left: statusBarProject ? (
        <WorkspaceStatusPath
          label={statusBarPathLabel}
          maxWidth={statusBarPathMaxWidth}
          onReveal={handleRevealStatusBarPath}
        />
      ) : null,
    }),
    [handleRevealStatusBarPath, statusBarPathLabel, statusBarPathMaxWidth, statusBarProject],
  );

  const workspaceBodyStyle = {
    "--workspace-side-panel-width": `${sidePanelLayout.sidePanelWidth}px`,
  } as CSSProperties;
  return (
    <WorkspaceNavigationProvider value={workspaceNavigation}>
      <main className="workspace-page" aria-label="workspace">
      <WindowTitlebar onRequestClose={handleRequestCloseWindow} />
      <section className="workspace-page__body" style={workspaceBodyStyle}>
        <HoverSidebar
          activeSection={activeSection}
          onSelectSection={handleSectionSelect}
          projectCatalog={hoverSidebarProjectCatalog}
          knowledgeCatalog={hoverSidebarKnowledgeCatalog}
          experienceCatalog={hoverSidebarExperienceCatalog}
          roleCatalog={hoverSidebarRoleCatalog}
          providerCatalog={hoverSidebarProviderCatalog}
          themeCatalog={hoverSidebarThemeCatalog}
          themeControl={themeControl}
          toolCatalog={hoverSidebarToolCatalog}
        />
        <WorkspaceSidePanel
          activeSection={activeSection}
          activeSettingsSectionId={activeSettingsSectionId}
          documentTabs={projectDocumentTabs}
          projectCatalog={sidePanelProjectCatalog}
          knowledgeProjectCatalog={sidePanelKnowledgeProjectCatalog}
          experienceProjectCatalog={sidePanelExperienceProjectCatalog}
          roleProjectCatalog={sidePanelRoleProjectCatalog}
          themeProjectCatalog={sidePanelThemeProjectCatalog}
          providerProjectCatalog={sidePanelProviderProjectCatalog}
          providerCatalog={providerCatalog}
          onOpenProvider={handleOpenProvider}
          toolCatalog={sidePanelToolCatalog}
          toolBrowser={toolBrowser}
          toolDocumentTabs={toolDocumentTabs}
          toolFolders={guardedToolFolders}
          isFunctionalModelGroupOpen={functionalModelSectionSelection.isSectionGroupOpen}
          sidePanelWidth={sidePanelLayout.sidePanelWidth}
          transitionDirection={sidePanelTransitionDirection}
          onReferenceProjectFile={handleReferenceProjectFile}
          onSelectFunctionalModelSection={handleSelectFunctionalModelSection}
          onSelectGithubSettings={handleSelectGithubSettings}
          onSelectLanguageSettings={handleSelectLanguageSettings}
          onSelectNetworkSettings={handleSelectNetworkSettings}
          onSelectTokenEstimationSettings={handleSelectTokenEstimationSettings}
          onToggleFunctionalModelGroup={functionalModelSectionSelection.toggleSectionGroup}
        />
        <div
          className={
            sidePanelLayout.isPanelResizing
              ? "workspace-page__panel-resizer workspace-page__panel-resizer--active"
              : "workspace-page__panel-resizer"
          }
          role="separator"
          aria-label="调整左侧面板宽度"
          aria-orientation="vertical"
          onPointerDown={sidePanelLayout.handleResizeStart}
          onDoubleClick={sidePanelLayout.resetWidth}
        />
        <WorkspaceCanvasPanel
          activeSection={activeSection}
          activeFunctionalModelSectionId={functionalModelSectionSelection.activeSectionId}
          activeSettingsSectionId={activeSettingsSectionId}
          activeThemeId={themeControl.activeThemeId}
          isThemeLoading={themeControl.isLoading}
          activeToolWorkspaceKey={activeToolWorkspaceKey}
          layoutPreferences={layoutPreferences}
          projectWorkspaceError={projectWorkspaceTabs.error}
          projectFileReferenceRequest={projectFileReferenceRequest}
          projectDocumentTabs={projectDocumentTabs}
          isRenamingProvider={
            providerCatalog.renamingProviderId === providerCatalog.selectedProviderId
          }
          isUpdatingProviderProtocol={
            providerCatalog.updatingProviderProtocolId ===
            providerCatalog.selectedProviderId
          }
          onRenameProvider={providerCatalog.renameProvider}
          onExpandProject={handleExpandProject}
          onCreateProject={handleCreateOverviewProject}
          onCreateKnowledgeProject={handleCreateKnowledgeProject}
          onCreateExperienceProject={handleCreateExperienceProject}
          onCreateRoleProject={handleCreateRoleProject}
          onCollapseProject={handleCollapseProject}
          onConfirmProjectSession={projectCatalog.confirmSessionSelection}
          onImportProjectFolder={handleImportOverviewProjectFolder}
          onApplyTheme={themeControl.onSelectTheme}
          onLayoutPreferenceChange={handleLayoutPreferenceChange}
          onPrepareProject={handlePrepareProject}
          onSelectProjectCategory={handleSelectProjectCategory}
          onSelectProject={handleSelectProject}
          onSelectFunctionalModelSection={handleSelectFunctionalModelSection}
          onOpenToolFolder={handleOpenToolFolder}
          onCollapseToolFolder={handleCollapseToolFolder}
          onSelectToolFolder={handleSelectToolFolder}
          onReloadToolFolders={toolFolders.reload}
          onRevealToolFolder={toolFolders.revealToolFolder}
          onSelectToolset={handleSelectToolset}
          onToolManifestSaved={toolFolders.reload}
          onUpdateProviderProtocol={providerCatalog.updateProviderProtocol}
          providerConfigState={providerConfigState}
          providerModelDiscovery={providerModelDiscovery}
          providerExpandedProjectId={providerExpandedProject?.project_id ?? null}
          providerProjectCategories={providerProjectCategories}
          providerProjects={providerProjects}
          providerSelectedCategoryId={providerSelectedCategoryId}
          providerSelectedProject={providerSelectedProject}
          providerSelectedSessionId={providerSelectedSessionId}
          expandedProjectId={projectExpandedProject?.project_id ?? null}
          projectCategories={projectCategories}
          projects={ordinaryProjects}
          knowledgeExpandedProjectId={knowledgeExpandedProject?.project_id ?? null}
          knowledgeProjectCategories={knowledgeProjectCategories}
          knowledgeProjects={knowledgeProjects}
          knowledgeSelectedCategoryId={knowledgeSelectedCategoryId}
          knowledgeSelectedProject={knowledgeSelectedProject}
          knowledgeSelectedSessionId={knowledgeSelectedSessionId}
          experienceExpandedProjectId={experienceExpandedProject?.project_id ?? null}
          experienceProjectCategories={experienceProjectCategories}
          experienceProjects={experienceProjects}
          experienceSelectedCategoryId={experienceSelectedCategoryId}
          experienceSelectedProject={experienceSelectedProject}
          experienceSelectedSessionId={experienceSelectedSessionId}
          roleExpandedProjectId={roleExpandedProject?.project_id ?? null}
          roleProjectCategories={roleProjectCategories}
          roleProjects={roleProjects}
          roleSelectedCategoryId={roleSelectedCategoryId}
          roleSelectedProject={roleSelectedProject}
          roleSelectedSessionId={roleSelectedSessionId}
          themeExpandedProjectId={themeExpandedProject?.project_id ?? null}
          themeProjectCategories={themeProjectCategories}
          themeProjects={themeProjects}
          themeSelectedCategoryId={themeSelectedCategoryId}
          themeSelectedProject={themeSelectedProject}
          themeSelectedSessionId={themeSelectedSessionId}
          selectedCategoryId={projectSelectedCategoryId}
          selectedProject={projectSelectedProject}
          selectedSessionId={projectSelectedSessionId}
          selectedProvider={providerCatalog.selectedProvider}
          selectedToolFolder={toolFolders.selectedFolder}
          expandedToolFolder={toolFolders.expandedFolder}
          selectedToolset={displayedToolset}
          toolFolders={toolFolders.items}
          toolFoldersError={toolFolders.error}
          toolFoldersReadonly={toolFolders.readonly}
          toolFoldersState={toolFolders.state}
          toolDocumentTabs={toolDocumentTabs}
          toolEntryFilePaths={toolEntryFilePaths}
          toolsets={toolCatalog.items}
          toolWorkspaceError={toolWorkspaceTabs.error}
        />
      </section>
      <WorkspaceUnsavedChangesModal modal={unsavedChangesModal} />
      </main>
    </WorkspaceNavigationProvider>
  );
}

function getProviderIdFromProject(rootPath: string) {
  return rootPath.replaceAll("\\", "/").split("/").filter(Boolean).pop() ?? null;
}

function canModifyToolFolders(toolset: ReturnType<typeof useToolCatalog>["selectedToolset"]) {
  if (!toolset) return false;
  return !toolset.readonly;
}

function buildProjectStatusPathLabel(rootPath: string, filePath: string | null | undefined) {
  const normalizedRoot = rootPath.trim();
  const normalizedFile = filePath?.trim().replace(/^[/\\]+/, "") ?? "";
  if (!normalizedFile) return normalizedRoot;
  if (!normalizedRoot) return normalizedFile;
  const separator = normalizedRoot.includes("\\") ? "\\" : "/";
  return `${normalizedRoot.replace(/[/\\]+$/, "")}${separator}${normalizedFile.replace(/[/\\]+/g, separator)}`;
}
