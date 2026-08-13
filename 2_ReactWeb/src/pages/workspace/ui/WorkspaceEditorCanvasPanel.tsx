import { memo, useCallback, useMemo, useState, type ReactNode } from "react";

import type { Project, ProjectCategory } from "../../../entities/project/model/project";
import type { ProjectFileReferenceRequest } from "../../../entities/project/model/projectFileDragData";
import type {
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { ChatPanel } from "../../../features/ai-panel/ui/ChatPanel";
import { DocumentEditorCanvas } from "../../../features/document-editor-canvas/ui/DocumentEditorCanvas";
import { isProjectConversationOverviewTab } from "../../../features/document-editor-canvas/model/documentTabClassification";
import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import type { ProjectEntryWarmupOptions } from "../../../features/project-entry/model/projectEntryWarmup";
import type { ProjectMarketScope } from "../../../features/project-market/model/projectMarket";
import { revealProjectFile } from "../../../services/project/revealProjectFile";
import { useWorkspaceConversationSelection } from "../model/useWorkspaceConversationSelection";
import { useWorkspaceDocumentActions } from "../model/useWorkspaceDocumentActions";
import { useWorkspaceEditorReferences } from "../model/useWorkspaceEditorReferences";
import { ProjectCategoryOverviewKeepAlive } from "./ProjectCategoryOverviewKeepAlive";
import { ProjectConversationOverviewDashboard } from "../../../features/project-category-overview/ui/ProjectConversationOverviewDashboard";
import { CollectionOverviewViewTabs } from "../../../features/project-category-overview/ui/CollectionOverviewViewTabs";
import { useRoleConfigurationEditor } from "../../../features/role-configuration/model/useRoleConfigurationEditor";
import { RoleCollectionOverview } from "../../../features/role-configuration/ui/RoleCollectionOverview";
import { RoleConfigurationDashboard } from "../../../features/role-configuration/ui/RoleConfigurationDashboard";
import { ThemeCollectionOverview } from "../../../features/theme-settings/ui/ThemeCollectionOverview";
import { ThemeSettingsPanel } from "../../../features/theme-settings/ui/ThemeSettingsPanel";
import { ThemeMarketBoard } from "../../../features/theme-market/ui/ThemeMarketBoard";
import { RoleMarketBoard } from "../../../features/role-market/ui/RoleMarketBoard";
import { ProviderMarketBoard } from "../../../features/provider-market/ui/ProviderMarketBoard";
import { useCollectionOverviewNavigation } from "../model/useCollectionOverviewNavigation";
import "../../../shared/ui/specialized-collection-overview/specialized-collection-overview.css";

type WorkspaceEditorCanvasPanelProps = {
  categories: ProjectCategory[];
  expandedProjectId: string | null;
  documentTabs: ReturnType<typeof useDocumentTabs>;
  isActive?: boolean;
  isRoleWorkspace?: boolean;
  isThemeWorkspace?: boolean;
  isProviderWorkspace?: boolean;
  providerConfigurationContent?: ReactNode;
  activeThemeId?: string | null;
  isThemeLoading?: boolean;
  layoutPreferences: WorkspaceLayoutPreferences;
  projectMarketScope?: ProjectMarketScope | null;
  onExpandProject: (
    projectId: string,
    options?: ProjectEntryWarmupOptions,
  ) => boolean | void | Promise<boolean | void>;
  onCreateProject?: () => Promise<void>;
  onCollapseProject: () => boolean | void | Promise<boolean | void>;
  onConfirmProjectSession: (projectId: string, sessionId: string | null) => void;
  onImportProjectFolder?: (rootPath: string) => Promise<void>;
  onApplyTheme?: (themeId: string) => void;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onPrepareProject?: (projectId: string) => void;
  onSelectCategory: (categoryId: string) => void;
  onSelectProject: (
    projectId: string,
    options?: ProjectEntryWarmupOptions,
  ) => boolean | void | Promise<boolean | void>;
  projects: Project[];
  projectFileReferenceRequest?: ProjectFileReferenceRequest | null;
  selectedCategoryId: string | null;
  selectedProject: Project | null;
  selectedSessionId: string | null;
  workspaceError?: string | null;
};

export const WorkspaceEditorCanvasPanel = memo(function WorkspaceEditorCanvasPanel({
  categories,
  expandedProjectId,
  documentTabs,
  isActive = true,
  isRoleWorkspace = false,
  isThemeWorkspace = false,
  isProviderWorkspace = false,
  providerConfigurationContent = null,
  activeThemeId = null,
  isThemeLoading = false,
  layoutPreferences,
  projectMarketScope = null,
  onExpandProject,
  onCreateProject,
  onConfirmProjectSession,
  onImportProjectFolder,
  onApplyTheme,
  onLayoutPreferenceChange,
  onPrepareProject,
  onSelectCategory,
  onSelectProject,
  projects,
  projectFileReferenceRequest = null,
  selectedCategoryId,
  selectedProject,
  selectedSessionId,
  workspaceError = null,
}: WorkspaceEditorCanvasPanelProps) {
  const desktopShell = useDesktopShell();
  const projectId = selectedProject?.project_id ?? null;
  const roleConfigurationEditor = useRoleConfigurationEditor(
    isRoleWorkspace && expandedProjectId ? projectId : null,
  );
  const [activeConversationMessage, setActiveConversationMessage] = useState<{
    messageId: string | null;
    projectId: string;
    sessionId: string;
  } | null>(null);
  const {
    chatSessionSelectionRequest,
    handleChatActiveSessionChange,
    handleChatSessionSelectionResult,
    handleCreateOverviewSession,
    handleEnterOverviewSession,
    handleSelectOverviewSession,
    visibleChatSession,
    sessionSelectionError,
  } = useWorkspaceConversationSelection({
    onConfirmProjectSession,
    onExpandProject,
    onSelectProject,
    projectId,
    selectedSessionId,
  });
  const {
    handleClearReferences,
    handleCreatePdfPageImageReference,
    handleCreatePresentationSlideImageReference,
    handleCreateSpreadsheetRangeImageReference,
    handleCreateTextReference,
    handleDraftReferencesChange,
    handleReferenceExternalPath,
    handleReferenceProjectFile,
    handleReferenceWorkspaceFile,
    handleRemoveFileReference,
    handleRemoveImageReference,
    handleRemoveTextReference,
    isImageReferenceUploadPending,
    references,
  } = useWorkspaceEditorReferences({
    documentTabs,
    projectId,
    sessionId: visibleChatSession?.projectId === projectId
      ? visibleChatSession.sessionId
      : null,
  });
  const {
    activeConversationDataFile,
    clientToolRegistrations,
    handleAiPanelWidthCommit,
    handleComposerHeightCommit,
    handleGenerateMarkdownDocx,
    handleOpenConversationBranches,
    handleOpenConversationDataFile: openConversationDataFile,
    handleOpenReference,
    handlePreviewHtmlCode,
    handleSaveProjectCodeBlock,
    visibleActiveTab,
    visibleActiveTabId,
    visibleProjectTabs,
  } = useWorkspaceDocumentActions({
    documentTabs,
    onLayoutPreferenceChange,
    projectId,
  });
  const handleOpenConversationDataFile = useCallback(async (
    sessionId: string,
    fileName: Parameters<typeof openConversationDataFile>[1],
  ) => {
    if (!projectId) return;
    if (expandedProjectId !== projectId) {
      const entered = await onExpandProject(projectId, { sessionId });
      if (entered === false) return;
    }
    openConversationDataFile(sessionId, fileName);
  }, [expandedProjectId, onExpandProject, openConversationDataFile, projectId]);

  const handleRevealOverviewProject = useCallback(async (targetProjectId: string) => {
    await revealProjectFile(targetProjectId, { path: "" });
  }, []);
  const handleSelectConversationMessage = useCallback((sessionId: string, messageId: string) => {
    if (!projectId) return;
    void handleSelectOverviewSession(projectId, sessionId, messageId);
  }, [handleSelectOverviewSession, projectId]);
  const handleSelectExternalBranchMessage = useCallback((
    targetProjectId: string,
    sessionId: string,
    messageId: string,
  ) => {
    void handleSelectOverviewSession(targetProjectId, sessionId, messageId);
  }, [handleSelectOverviewSession]);
  const handleEnterConversationBranches = useCallback(async (
    targetProjectId: string,
    sessionId: string | null,
  ) => {
    const entered = await onExpandProject(targetProjectId, { sessionId });
    if (entered === false) return;
    handleOpenConversationBranches(targetProjectId);
  }, [handleOpenConversationBranches, onExpandProject]);
  const handleOpenCurrentConversationBranches = useCallback(() => {
    if (!projectId) return;
    void handleEnterConversationBranches(
      projectId,
      visibleChatSession?.projectId === projectId
        ? visibleChatSession.sessionId
        : selectedSessionId,
    );
  }, [handleEnterConversationBranches, projectId, selectedSessionId, visibleChatSession]);
  const handleOpenCurrentConversationOverview = useCallback(() => {
    if (!projectId) return;
    documentTabs.ensureProjectConversationOverview(projectId, { activate: true });
  }, [documentTabs.ensureProjectConversationOverview, projectId]);
  const handleActiveUserMessageChange = useCallback((
    targetProjectId: string,
    sessionId: string,
    messageId: string | null,
  ) => {
    setActiveConversationMessage((current) => {
      if (
        current?.projectId === targetProjectId &&
        current.sessionId === sessionId &&
        current.messageId === messageId
      ) {
        return current;
      }
      return { messageId, projectId: targetProjectId, sessionId };
    });
  }, []);
  const shouldShowCategoryOverview = !expandedProjectId;
  const collectionKind = isRoleWorkspace
    ? "role" as const
    : isThemeWorkspace
      ? "theme" as const
      : isProviderWorkspace
        ? "provider" as const
      : null;
  const {
    activeView: collectionOverviewView,
    commonLayoutPreferences,
    handleCommonLayoutPreferenceChange,
    selectView: handleCollectionOverviewViewChange,
  } = useCollectionOverviewNavigation({
    categoryId: collectionKind ? selectedCategoryId : null,
    layoutPreferences,
    onLayoutPreferenceChange,
    onSelectProject,
    projects,
    selectedProjectId: selectedProject?.project_id ?? null,
  });
  const selectedCategoryProjects = useMemo(
    () => selectedCategoryId
      ? projects.filter((project) => project.category_id === selectedCategoryId)
      : [],
    [projects, selectedCategoryId],
  );
  const categoryOverviewContent = (
    <ProjectCategoryOverviewKeepAlive
      activeConversationMessageId={
        activeConversationMessage?.projectId === visibleChatSession?.projectId
          && activeConversationMessage?.sessionId === visibleChatSession?.sessionId
          ? activeConversationMessage?.messageId ?? null
          : null
      }
      categories={categories}
      isActive={
        isActive
        && shouldShowCategoryOverview
        && (
          !collectionKind
          || (
            collectionOverviewView !== "specialized"
            && collectionOverviewView !== "online"
          )
        )
      }
      enableExternalBranchView={collectionKind ? false : undefined}
      enableExternalOverviewViews={collectionKind ? true : undefined}
      layoutPreferences={collectionKind ? commonLayoutPreferences : layoutPreferences}
      marketScope={projectMarketScope}
      onActivateProject={onSelectProject}
      onCreateProject={onCreateProject}
      onCreateSession={handleCreateOverviewSession}
      onEnterSession={handleEnterOverviewSession}
      onImportProjectFolder={onImportProjectFolder}
      onLayoutPreferenceChange={
        collectionKind
          ? handleCommonLayoutPreferenceChange
          : onLayoutPreferenceChange
      }
      onOpenConversationBranches={handleEnterConversationBranches}
      onPrepareProject={onPrepareProject}
      onRevealProject={handleRevealOverviewProject}
      onSelectConversationMessage={handleSelectExternalBranchMessage}
      onSelectExportDirectory={desktopShell.selectProjectFolder}
      onSelectCategory={onSelectCategory}
      onSelectSession={handleSelectOverviewSession}
      projects={projects}
      selectedCategoryId={selectedCategoryId}
      showOverviewTabs={!collectionKind}
      visibleSession={visibleChatSession}
    />
  );
  const projectConversationOverviewContent = (
    <ProjectConversationOverviewDashboard
      isActive={
        isActive
        && Boolean(expandedProjectId)
        && isProjectConversationOverviewTab(visibleActiveTab)
      }
      onCreateSession={handleCreateOverviewSession}
      onOpenConversationBranches={handleEnterConversationBranches}
      onRevealProject={handleRevealOverviewProject}
      onSelectSession={handleSelectOverviewSession}
      projectId={projectId}
      visibleSession={visibleChatSession}
    />
  );
  const roleConfigurationContent = isRoleWorkspace && projectId ? (
    <RoleConfigurationDashboard
      editor={roleConfigurationEditor}
      projectName={selectedProject?.name ?? "角色"}
    />
  ) : null;
  const themeId = isThemeWorkspace ? projectId : null;
  const themeConfigurationContent = isThemeWorkspace && projectId && themeId ? (
    <ThemeSettingsPanel
      activeThemeId={activeThemeId}
      themeId={themeId}
    />
  ) : null;
  const specializedOverviewContent = collectionKind === "role" ? (
    <RoleCollectionOverview
      isActive={
        isActive
        && shouldShowCategoryOverview
        && collectionOverviewView === "specialized"
      }
      onOpenProject={(targetProjectId) => {
        void onExpandProject(targetProjectId);
      }}
      onSelectProject={(targetProjectId) => {
        void onSelectProject(targetProjectId);
      }}
      projects={selectedCategoryProjects}
      selectedProjectId={selectedProject?.project_id ?? null}
    />
  ) : collectionKind === "theme" ? (
    <ThemeCollectionOverview
      activeThemeId={activeThemeId}
      isActive={
        isActive
        && shouldShowCategoryOverview
        && collectionOverviewView === "specialized"
      }
      isApplyingTheme={isThemeLoading}
      onApplyTheme={onApplyTheme}
      onOpenProject={(targetProjectId) => {
        void onExpandProject(targetProjectId);
      }}
      onSelectProject={(targetProjectId) => {
        void onSelectProject(targetProjectId);
      }}
      projects={selectedCategoryProjects}
      selectedProjectId={selectedProject?.project_id ?? null}
    />
  ) : collectionKind === "provider" ? (
    providerConfigurationContent
  ) : null;
  const onlineMarketContent = isThemeWorkspace ? (
    <ThemeMarketBoard
      categories={categories}
      isActive={
        isActive
        && shouldShowCategoryOverview
        && collectionOverviewView === "online"
      }
      selectedCategoryId={selectedCategoryId}
    />
  ) : isRoleWorkspace ? (
    <RoleMarketBoard
      categories={categories}
      isActive={
        isActive
        && shouldShowCategoryOverview
        && collectionOverviewView === "online"
      }
      selectedCategoryId={selectedCategoryId}
    />
  ) : isProviderWorkspace ? (
    <ProviderMarketBoard
      categories={categories}
      isActive={
        isActive
        && shouldShowCategoryOverview
        && collectionOverviewView === "online"
      }
      selectedCategoryId={selectedCategoryId}
    />
  ) : null;
  const overviewContent = collectionKind ? (
    <div className="collection-dashboard-host">
      <CollectionOverviewViewTabs
        activeView={collectionOverviewView}
        disabled={!selectedProject}
        kind={collectionKind}
        onChange={handleCollectionOverviewViewChange}
      />
      <div className="collection-dashboard-host__body">
        <div
          className={
            collectionOverviewView === "specialized"
              ? "collection-dashboard-host__view"
              : "collection-dashboard-host__view collection-dashboard-host__view--hidden"
          }
          aria-hidden={collectionOverviewView === "specialized" ? undefined : "true"}
        >
          {specializedOverviewContent}
        </div>
        <div
          className={
            collectionOverviewView === "online"
              ? "collection-dashboard-host__view"
              : "collection-dashboard-host__view collection-dashboard-host__view--hidden"
          }
          aria-hidden={collectionOverviewView === "online" ? undefined : "true"}
        >
          {onlineMarketContent}
        </div>
        <div
          className={
            collectionOverviewView !== "specialized" && collectionOverviewView !== "online"
              ? "collection-dashboard-host__view"
              : "collection-dashboard-host__view collection-dashboard-host__view--hidden"
          }
          aria-hidden={
            collectionOverviewView !== "specialized" && collectionOverviewView !== "online"
              ? undefined
              : "true"
          }
        >
          {categoryOverviewContent}
        </div>
      </div>
    </div>
  ) : categoryOverviewContent;
  const assistantPanel = useMemo(() => (
    <ChatPanel
      activeConversationDataFile={activeConversationDataFile}
      clientToolRegistrations={clientToolRegistrations}
      composerInitialHeight={layoutPreferences.composerHeight}
      references={references}
      isActive={isActive}
      isImageReferenceUploadPending={isImageReferenceUploadPending}
      onActiveUserMessageChange={handleActiveUserMessageChange}
      onActiveSessionChange={handleChatActiveSessionChange}
      onSessionSelectionResult={handleChatSessionSelectionResult}
      onClearReferences={handleClearReferences}
      onComposerHeightCommit={handleComposerHeightCommit}
      onDraftReferencesChange={handleDraftReferencesChange}
      onOpenConversationBranches={handleOpenCurrentConversationBranches}
      onOpenConversationOverview={handleOpenCurrentConversationOverview}
      onOpenConversationDataFile={handleOpenConversationDataFile}
      onOpenReference={handleOpenReference}
      onPreviewHtmlCode={handlePreviewHtmlCode}
      onReferenceExternalPath={handleReferenceExternalPath}
      onReferenceProjectFile={handleReferenceProjectFile}
      onRemoveFileReference={handleRemoveFileReference}
      onRemoveImageReference={handleRemoveImageReference}
      onRemoveTextReference={handleRemoveTextReference}
      onSaveCodeBlock={handleSaveProjectCodeBlock}
      onSelectExportDirectory={desktopShell.selectProjectFolder}
      preferredSessionId={selectedSessionId}
      projectFileReferenceRequest={projectFileReferenceRequest}
      projectId={projectId}
      projectRootPath={selectedProject?.root_path ?? ""}
      sessionSelectionError={sessionSelectionError}
      sessionSelectionRequest={chatSessionSelectionRequest}
    />
  ), [
    activeConversationDataFile,
    chatSessionSelectionRequest,
    clientToolRegistrations,
    desktopShell.selectProjectFolder,
    handleChatActiveSessionChange,
    handleActiveUserMessageChange,
    handleChatSessionSelectionResult,
    handleClearReferences,
    handleComposerHeightCommit,
    handleDraftReferencesChange,
    handleOpenCurrentConversationBranches,
    handleOpenCurrentConversationOverview,
    handleOpenConversationDataFile,
    handleOpenReference,
    handlePreviewHtmlCode,
    handleReferenceExternalPath,
    handleReferenceProjectFile,
    handleRemoveFileReference,
    handleRemoveImageReference,
    handleRemoveTextReference,
    handleSaveProjectCodeBlock,
    isActive,
    isImageReferenceUploadPending,
    layoutPreferences.composerHeight,
    projectFileReferenceRequest,
    projectId,
    selectedProject?.root_path,
    selectedSessionId,
    sessionSelectionError,
    references,
  ]);

  return (
    <DocumentEditorCanvas
      activeConversationMessageId={
        activeConversationMessage?.projectId === projectId &&
        activeConversationMessage.sessionId === visibleChatSession?.sessionId
          ? activeConversationMessage.messageId
          : null
      }
      activeConversationSessionId={visibleChatSession?.sessionId ?? null}
      activeTab={shouldShowCategoryOverview ? null : visibleActiveTab}
      activeTabId={shouldShowCategoryOverview ? null : visibleActiveTabId}
      aiPanelInitialWidth={layoutPreferences.aiPanelWidth}
      assistantPanel={assistantPanel}
      emptyMessage={null}
      onAiPanelWidthCommit={handleAiPanelWidthCommit}
      onCloseAllTabs={() => documentTabs.closeAllTabs({ preservePinned: true })}
      onCloseOtherTabs={documentTabs.closeOtherTabs}
      onCloseTab={documentTabs.closeTab}
      onCreatePdfPageImageReference={handleCreatePdfPageImageReference}
      onCreatePresentationSlideImageReference={handleCreatePresentationSlideImageReference}
      onCreateSpreadsheetRangeImageReference={handleCreateSpreadsheetRangeImageReference}
      onCreateTextReference={handleCreateTextReference}
      onGenerateMarkdownDocx={handleGenerateMarkdownDocx}
      onMarkDirty={documentTabs.markTabDirty}
      onMarkMissing={documentTabs.markTabMissing}
      onOverwriteExternalChange={documentTabs.overwriteExternalChange}
      onReferenceWorkspaceFile={handleReferenceWorkspaceFile}
      onSaveCodeBlock={handleSaveProjectCodeBlock}
      onSaveTab={documentTabs.saveTab}
      onSaveTabAs={documentTabs.saveTabAs}
      onSelectConversationMessage={handleSelectConversationMessage}
      onSelectExportDirectory={desktopShell.selectProjectFolder}
      onSelectTab={documentTabs.selectTab}
      onUpdateContent={documentTabs.updateTabContent}
      persistentEmptyContent={overviewContent}
      persistentEmptyContentVisible={shouldShowCategoryOverview}
      projectConversationOverviewContent={projectConversationOverviewContent}
      roleConfigurationContent={roleConfigurationContent}
      themeConfigurationContent={themeConfigurationContent}
      projectRootPath={selectedProject?.root_path ?? ""}
      statusMessage={workspaceError}
      tabs={shouldShowCategoryOverview ? [] : visibleProjectTabs}
    />
  );
});
