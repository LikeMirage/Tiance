import { memo, useCallback, useEffect, useMemo, useState } from "react";

import type { ToolFolder, Toolset } from "../../../entities/tool/model/toolset";
import type {
  WorkspaceLayoutPreferences,
  WorkspaceLayoutPreferenceUpdate,
  ToolOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { ChatPanel } from "../../../features/ai-panel/ui/ChatPanel";
import { DocumentEditorCanvas } from "../../../features/document-editor-canvas/ui/DocumentEditorCanvas";
import { useDesktopShell } from "../../../features/desktop-shell/model/useDesktopShell";
import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";
import { ToolsetOverview } from "../../../features/toolset-overview/ui/ToolsetOverview";
import { ToolOverviewViewTabs } from "../../../features/toolset-overview/ui/ToolOverviewViewTabs";
import { ToolMarketBoard } from "../../../features/tool-market/ui/ToolMarketBoard";
import { preloadProjectEntry } from "../../../features/project-entry/model/projectEntryWarmup";
import {
  toolFoldersToProjects,
  toolsetsToProjectCategories,
} from "../model/toolProjectCollectionAdapters";
import { useWorkspaceConversationSelection } from "../model/useWorkspaceConversationSelection";
import { useWorkspaceDocumentActions } from "../model/useWorkspaceDocumentActions";
import { useWorkspaceEditorReferences } from "../model/useWorkspaceEditorReferences";
import { useToolOverviewNavigation } from "../model/useToolOverviewNavigation";
import { ProjectCategoryOverviewKeepAlive } from "./ProjectCategoryOverviewKeepAlive";

type WorkspaceToolCanvasPanelProps = {
  activeWorkspaceKey: string | null;
  folders: ToolFolder[];
  documentTabs: ReturnType<typeof useDocumentTabs>;
  folderError?: string | null;
  folderState: "idle" | "loading" | "ready" | "error";
  expandedToolFolder: ToolFolder | null;
  isActive?: boolean;
  layoutPreferences: WorkspaceLayoutPreferences;
  onOpenFolder: (folderId: string) => void;
  onCollapseFolder: () => Promise<boolean>;
  onSelectFolder: (folderId: string) => void;
  onLayoutPreferenceChange: (update: WorkspaceLayoutPreferenceUpdate) => void;
  onReloadFolders: () => void;
  onRevealFolder: (folderId: string) => Promise<void>;
  onSelectToolset: (toolsetId: string) => void;
  onToolManifestSaved?: () => void;
  readonly: boolean;
  selectedToolFolder: ToolFolder | null;
  selectedToolset: Toolset | null;
  toolEntryFilePaths: string[];
  toolsets: Toolset[];
  workspaceError?: string | null;
};

export const WorkspaceToolCanvasPanel = memo(function WorkspaceToolCanvasPanel({
  activeWorkspaceKey,
  folders,
  documentTabs,
  folderError = null,
  folderState,
  expandedToolFolder,
  isActive = true,
  layoutPreferences,
  onOpenFolder,
  onCollapseFolder,
  onSelectFolder,
  onLayoutPreferenceChange,
  onReloadFolders,
  onRevealFolder,
  onSelectToolset,
  onToolManifestSaved,
  readonly,
  selectedToolFolder,
  selectedToolset,
  toolEntryFilePaths,
  toolsets,
  workspaceError = null,
}: WorkspaceToolCanvasPanelProps) {
  const desktopShell = useDesktopShell();
  const projectId = selectedToolFolder?.project_id ?? null;
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeConversationMessage, setActiveConversationMessage] = useState<{
    messageId: string | null;
    projectId: string;
    sessionId: string;
  } | null>(null);
  useEffect(() => {
    setActiveSessionId(null);
  }, [projectId]);
  const projectCategories = useMemo(
    () => toolsetsToProjectCategories(toolsets),
    [toolsets],
  );
  const projects = useMemo(
    () => toolFoldersToProjects(folders),
    [folders],
  );
  const findFolderByProjectId = useCallback(
    (targetProjectId: string) =>
      folders.find((folder) => folder.project_id === targetProjectId) ?? null,
    [folders],
  );
  const handleSelectToolProject = useCallback((targetProjectId: string) => {
    const folder = findFolderByProjectId(targetProjectId);
    if (!folder) return false;
    onSelectFolder(folder.project_id);
    return true;
  }, [findFolderByProjectId, onSelectFolder]);
  const handleExpandToolProject = useCallback((targetProjectId: string) => {
    const folder = findFolderByProjectId(targetProjectId);
    if (!folder) return false;
    onSelectFolder(folder.project_id);
    onOpenFolder(folder.project_id);
    return true;
  }, [findFolderByProjectId, onOpenFolder, onSelectFolder]);
  const handlePrepareToolProject = useCallback((targetProjectId: string) => {
    if (!findFolderByProjectId(targetProjectId)) return;
    void preloadProjectEntry(targetProjectId);
  }, [findFolderByProjectId]);
  const handleConfirmToolSession = useCallback((
    targetProjectId: string,
    sessionId: string | null,
  ) => {
    if (targetProjectId === projectId) {
      setActiveSessionId(sessionId);
    }
  }, [projectId]);
  const {
    chatSessionSelectionRequest,
    handleChatActiveSessionChange,
    handleChatSessionSelectionResult,
    handleCreateOverviewSession,
    handleEnterOverviewSession,
    handleSelectOverviewSession,
    sessionSelectionError,
    visibleChatSession,
  } = useWorkspaceConversationSelection({
    onConfirmProjectSession: handleConfirmToolSession,
    onExpandProject: handleExpandToolProject,
    onSelectProject: handleSelectToolProject,
    persistWorkspaceSelection: false,
    projectId,
    selectedSessionId: activeSessionId,
  });
  const scopedTabs = useMemo(
    () => activeWorkspaceKey
      ? documentTabs.tabs.filter((tab) => tab.fileSource?.key === activeWorkspaceKey)
      : [],
    [activeWorkspaceKey, documentTabs.tabs],
  );
  const scopedActiveTab = useMemo(
    () => documentTabs.activeTab?.fileSource?.key === activeWorkspaceKey
      ? documentTabs.activeTab
      : null,
    [activeWorkspaceKey, documentTabs.activeTab],
  );
  const scopedActiveTabId = scopedActiveTab?.id ?? null;
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
    sessionId: activeSessionId,
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
  const handleOpenConversationDataFile = useCallback((
    sessionId: string,
    fileName: Parameters<typeof openConversationDataFile>[1],
  ) => {
    if (!projectId) return;
    if (expandedToolFolder?.project_id !== projectId) {
      const entered = handleExpandToolProject(projectId);
      if (!entered) return;
    }
    openConversationDataFile(sessionId, fileName);
  }, [expandedToolFolder?.project_id, handleExpandToolProject, openConversationDataFile, projectId]);
  const handleSaveTab = useCallback(async (id: string, contentSnapshot?: string) => {
    const tab = documentTabs.tabs.find((item) => item.id === id) ?? null;
    const didSave = await documentTabs.saveTab(id, contentSnapshot);
    if (
      didSave &&
      (
        tab?.fileSource?.kind === "tool-dashboard" ||
        tab?.filePath === ".tool/tool.json"
      )
    ) {
      onToolManifestSaved?.();
    }
    return didSave;
  }, [documentTabs, onToolManifestSaved]);
  const handleActiveUserMessageChange = useCallback((
    targetProjectId: string,
    sessionId: string,
    messageId: string | null,
  ) => {
    setActiveConversationMessage((current) => {
      if (
        current?.projectId === targetProjectId
        && current.sessionId === sessionId
        && current.messageId === messageId
      ) {
        return current;
      }
      return { messageId, projectId: targetProjectId, sessionId };
    });
  }, []);

  const {
    activeView: overviewView,
    commonLayoutPreferences,
    handleCommonLayoutPreferenceChange,
    selectView: handleToolOverviewViewChange,
  } = useToolOverviewNavigation({
    layoutPreferences,
    onLayoutPreferenceChange,
    onSelectProject: handleSelectToolProject,
    projects,
    selectedProjectId: projectId,
    selectedToolsetId: selectedToolset?.category_id ?? null,
  });
  const handleOpenExternalToolView = useCallback(async (
    view: Exclude<ToolOverviewView, "tools" | "projects">,
  ) => {
    if (!projectId) return;
    if (expandedToolFolder) {
      const didCollapse = await onCollapseFolder();
      if (!didCollapse) return;
    }
    handleToolOverviewViewChange(view, projectId);
  }, [
    expandedToolFolder,
    handleToolOverviewViewChange,
    onCollapseFolder,
    projectId,
  ]);

  const assistantPanel = useMemo(() => (
    <ChatPanel
      activeConversationDataFile={activeConversationDataFile}
      clientToolRegistrations={clientToolRegistrations}
      composerInitialHeight={layoutPreferences.composerHeight}
      isActive={isActive}
      isImageReferenceUploadPending={isImageReferenceUploadPending}
      onActiveUserMessageChange={handleActiveUserMessageChange}
      onActiveSessionChange={handleChatActiveSessionChange}
      onSessionSelectionResult={handleChatSessionSelectionResult}
      onClearReferences={handleClearReferences}
      onComposerHeightCommit={handleComposerHeightCommit}
      onDraftReferencesChange={handleDraftReferencesChange}
      onOpenConversationBranches={() => void handleOpenExternalToolView("branches")}
      onOpenConversationOverview={() => void handleOpenExternalToolView("conversation")}
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
      preferredSessionId={activeSessionId}
      projectId={selectedToolFolder?.project_id ?? null}
      projectRootPath={selectedToolFolder?.root_path ?? ""}
      references={references}
      sessionSelectionError={sessionSelectionError}
      sessionSelectionRequest={chatSessionSelectionRequest}
    />
  ), [
    activeSessionId,
    isActive,
    activeConversationDataFile,
    chatSessionSelectionRequest,
    clientToolRegistrations,
    desktopShell.selectProjectFolder,
    handleChatActiveSessionChange,
    handleChatSessionSelectionResult,
    handleActiveUserMessageChange,
    handleClearReferences,
    handleComposerHeightCommit,
    handleDraftReferencesChange,
    handleOpenExternalToolView,
    handleOpenConversationDataFile,
    handleOpenReference,
    handlePreviewHtmlCode,
    handleReferenceExternalPath,
    handleReferenceProjectFile,
    handleRemoveFileReference,
    handleRemoveImageReference,
    handleRemoveTextReference,
    handleSaveProjectCodeBlock,
    isImageReferenceUploadPending,
    layoutPreferences.composerHeight,
    projectId,
    references,
    selectedToolFolder?.project_id,
    selectedToolFolder?.root_path,
    sessionSelectionError,
  ]);

  const toolOverviewContent = (
    <ToolsetOverview
      error={folderError ?? workspaceError}
      folders={folders}
      isActive={isActive}
      onOpenFolder={onOpenFolder}
      onSelectFolder={onSelectFolder}
      onReload={onReloadFolders}
      onRevealFolder={onRevealFolder}
      readonly={readonly}
      selectedFolderId={selectedToolFolder?.project_id ?? null}
      state={folderState}
      toolset={selectedToolset}
    />
  );
  const toolMarketContent = (
    <ToolMarketBoard
      categories={projectCategories}
      isActive={isActive && overviewView === "online"}
      onInstalled={onReloadFolders}
      selectedCategoryId={selectedToolset?.category_id ?? null}
    />
  );
  const handleRevealProject = useCallback(async (targetProjectId: string) => {
    const folder = findFolderByProjectId(targetProjectId);
    if (!folder) return;
    await onRevealFolder(folder.project_id);
  }, [findFolderByProjectId, onRevealFolder]);
  const handleOpenConversationBranchesForProject = useCallback(async (
    targetProjectId: string,
  ) => {
    const folder = findFolderByProjectId(targetProjectId);
    if (!folder) return;
    onSelectFolder(folder.project_id);
    onOpenFolder(folder.project_id);
    handleOpenConversationBranches(targetProjectId);
  }, [
    findFolderByProjectId,
    handleOpenConversationBranches,
    onOpenFolder,
    onSelectFolder,
  ]);
  const handleSelectExternalBranchMessage = useCallback((
    targetProjectId: string,
    sessionId: string,
    messageId: string,
  ) => {
    void handleSelectOverviewSession(targetProjectId, sessionId, messageId);
  }, [handleSelectOverviewSession]);
  const conversationOverviewContent = (
    <ProjectCategoryOverviewKeepAlive
      activeConversationMessageId={
        activeConversationMessage
          && activeConversationMessage.projectId === visibleChatSession?.projectId
          && activeConversationMessage.sessionId === visibleChatSession?.sessionId
          ? activeConversationMessage.messageId
          : null
      }
      categories={projectCategories}
      enableExternalOverviewViews
      isActive={isActive && overviewView !== "tools" && overviewView !== "online"}
      layoutPreferences={commonLayoutPreferences}
      onActivateProject={handleSelectToolProject}
      onCreateSession={handleCreateOverviewSession}
      onEnterSession={handleEnterOverviewSession}
      onLayoutPreferenceChange={handleCommonLayoutPreferenceChange}
      onOpenConversationBranches={handleOpenConversationBranchesForProject}
      onPrepareProject={handlePrepareToolProject}
      onRevealProject={handleRevealProject}
      onSelectConversationMessage={handleSelectExternalBranchMessage}
      onSelectExportDirectory={desktopShell.selectProjectFolder}
      onSelectCategory={onSelectToolset}
      onSelectSession={handleSelectOverviewSession}
      projects={projects}
      selectedCategoryId={selectedToolset?.category_id ?? null}
      visibleSession={visibleChatSession}
    />
  );
  const overviewContent = (
    <div className="tool-dashboard-host">
      <ToolOverviewViewTabs
        activeView={overviewView}
        disabled={!selectedToolFolder}
        onChange={handleToolOverviewViewChange}
      />
      <div className="tool-dashboard-host__body">
        <div
          className={
            overviewView === "tools"
              ? "tool-dashboard-host__view"
              : "tool-dashboard-host__view tool-dashboard-host__view--hidden"
          }
          aria-hidden={overviewView === "tools" ? undefined : "true"}
        >
          {toolOverviewContent}
        </div>
        <div
          className={
            overviewView === "online"
              ? "tool-dashboard-host__view"
              : "tool-dashboard-host__view tool-dashboard-host__view--hidden"
          }
          aria-hidden={overviewView === "online" ? undefined : "true"}
        >
          {toolMarketContent}
        </div>
        <div
          className={
            overviewView !== "tools" && overviewView !== "online"
              ? "tool-dashboard-host__view"
              : "tool-dashboard-host__view tool-dashboard-host__view--hidden"
          }
          aria-hidden={overviewView !== "tools" && overviewView !== "online" ? undefined : "true"}
        >
          {conversationOverviewContent}
        </div>
      </div>
    </div>
  );

  return (
    <DocumentEditorCanvas
      activeTab={expandedToolFolder ? visibleActiveTab ?? scopedActiveTab : null}
      activeTabId={expandedToolFolder ? visibleActiveTabId ?? scopedActiveTabId : null}
      aiPanelInitialWidth={layoutPreferences.aiPanelWidth}
      assistantPanel={assistantPanel}
      emptyMessage={null}
      onAiPanelWidthCommit={handleAiPanelWidthCommit}
      onCreatePdfPageImageReference={handleCreatePdfPageImageReference}
      onCreatePresentationSlideImageReference={handleCreatePresentationSlideImageReference}
      onCreateSpreadsheetRangeImageReference={handleCreateSpreadsheetRangeImageReference}
      onCreateTextReference={handleCreateTextReference}
      onGenerateMarkdownDocx={handleGenerateMarkdownDocx}
      onReferenceWorkspaceFile={handleReferenceWorkspaceFile}
      onSaveCodeBlock={handleSaveProjectCodeBlock}
      onSelectExportDirectory={desktopShell.selectProjectFolder}
      persistentEmptyContent={overviewContent}
      persistentEmptyContentVisible={!expandedToolFolder}
      statusMessage={workspaceError}
      tabs={expandedToolFolder ? visibleProjectTabs : []}
      toolEntryCandidates={toolEntryFilePaths}
      onCloseTab={documentTabs.closeTab}
      onCloseOtherTabs={documentTabs.closeOtherTabs}
      onCloseAllTabs={() => documentTabs.closeAllTabs({ preservePinned: true })}
      onMarkDirty={documentTabs.markTabDirty}
      onMarkMissing={documentTabs.markTabMissing}
      onOverwriteExternalChange={documentTabs.overwriteExternalChange}
      onSaveTab={handleSaveTab}
      onSaveTabAs={documentTabs.saveTabAs}
      onSelectTab={documentTabs.selectTab}
      onUpdateContent={documentTabs.updateTabContent}
    />
  );
});
